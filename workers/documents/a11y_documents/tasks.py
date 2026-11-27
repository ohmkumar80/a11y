"""The ``docs.render_report`` Celery task: renders ONE report and stores it only if it passes its gate.

Gates (PROJECT_PLAN 2.5): PDF -> veraPDF PDF/UA-1; DOCX -> structural accessibility check; CSV -> schema check.
A file that fails its gate is never stored or offered: the report becomes FAILED with a plain explanation.
Idempotent: a finished report is never re-rendered, so a redelivered task cannot change a file that was already
delivered (a template change affects NEW reports only)."""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import uuid

from a11y_core.celery_app import celery_app
from a11y_core.db import dispose_engines, tenant_session
from a11y_core.models import Report
from a11y_core.vpat import VpatCriterion
from sqlalchemy import text, update

from .csv_export import build_csv, check_csv
from .data import load_audit_data
from .docx_check import check_docx
from .docx_export import audit_docx, vpat_docx
from .pdf import ReportTemplateError, render_pdf_ua
from .registry import TEMPLATES, render_html
from .verapdf import VeraPdfUnavailable, validate_pdf_ua
from .vpat import build_doc

log = logging.getLogger(__name__)
MAX_BYTES = 25 * 1024 * 1024
GATE_FAILED = "We could not produce a file that passes our accessibility checks, so we did not deliver it. Our team has been notified."


class GateFailed(Exception):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def _docx_bytes(doc) -> bytes:
    b = io.BytesIO()
    doc.save(b)
    return b.getvalue()


async def _produce(db, org_id: uuid.UUID, rep) -> tuple[bytes, str, dict]:
    """(content, template version, validation summary) for a report row; raises GateFailed."""
    org_name = (await db.execute(text("SELECT name FROM organizations"))).scalar_one()
    kind = rep.kind
    if kind.startswith("audit"):
        if kind == "audit_csv":
            data = await build_csv(db, rep.scan_id, rep.standard)
            if problems := check_csv(data):
                raise GateFailed(problems)
            return data, "csv@v1", {"gate": "csv-schema", "passed": True}
        d = await load_audit_data(db, rep.scan_id, rep.standard, organization=org_name)
        tv = TEMPLATES["audit_report"].version_id
        d.template_version = tv
        if kind == "audit_docx":
            data = _docx_bytes(audit_docx(d))
            if problems := check_docx(data):
                raise GateFailed(problems)
            return data, tv, {"gate": "docx-structure", "passed": True}
        pdf, validation = _pdf(render_html("audit_report", d))
        return pdf, tv, validation
    # VPAT: needs a signed-off draft
    v = (
        await db.execute(text("SELECT * FROM vpat_reports WHERE id=:i"), {"i": rep.vpat_id})
    ).first()
    scan = (
        await db.execute(text("SELECT * FROM scan_jobs WHERE id=:i"), {"i": rep.scan_id})
    ).first()
    if v is None or scan is None or v.status != "SIGNED_OFF":
        raise GateFailed(["the VPAT has not been signed off"])
    doc = build_doc(v, scan, org_name, [VpatCriterion(**c) for c in v.criteria])
    tv = TEMPLATES["vpat"].version_id
    doc.template_version = tv
    if kind == "vpat_docx":
        data = _docx_bytes(vpat_docx(doc))
        if problems := check_docx(data):
            raise GateFailed(problems)
        return data, tv, {"gate": "docx-structure", "passed": True}
    pdf, validation = _pdf(render_html("vpat", doc))
    return pdf, tv, validation


def _pdf(html: str) -> tuple[bytes, dict]:
    pdf = render_pdf_ua(html)
    res = validate_pdf_ua(pdf)
    if not res.compliant:
        raise GateFailed([res.summary()])
    return pdf, {
        "gate": "veraPDF PDF/UA-1",
        "passed": True,
        "rules_passed": res.passed_rules,
        "version": res.tool_version,
    }


async def render_report(org_id: uuid.UUID, report_id: uuid.UUID) -> str:
    async with tenant_session(org_id) as db:
        rep = (
            await db.execute(text("SELECT * FROM reports WHERE id=:i FOR UPDATE"), {"i": report_id})
        ).first()
        if rep is None:
            return "MISSING"
        if rep.status in ("READY", "FAILED"):
            return rep.status
        await db.execute(text("UPDATE reports SET status='RUNNING' WHERE id=:i"), {"i": report_id})
    try:
        async with tenant_session(org_id) as db:
            rep = (
                await db.execute(text("SELECT * FROM reports WHERE id=:i"), {"i": report_id})
            ).first()
            content, tv, validation = await _produce(db, org_id, rep)
            if len(content) > MAX_BYTES:
                raise GateFailed([f"the file is larger than {MAX_BYTES // 1024 // 1024} MB"])
            await db.execute(
                update(Report)
                .where(Report.id == report_id)
                .values(
                    status="READY",
                    content=content,
                    size_bytes=len(content),
                    sha256=hashlib.sha256(content).hexdigest(),
                    template_version=tv,
                    validation=validation,
                    finished_at=text("now()"),
                    error_code=None,
                    error_detail=None,
                )
            )
        return "READY"
    except (GateFailed, ReportTemplateError, VeraPdfUnavailable) as e:
        log.error("report %s failed its gate: %s", report_id, e)
        code, detail = (
            ("validation_failed", GATE_FAILED)
            if not isinstance(e, VeraPdfUnavailable)
            else (
                "validator_unavailable",
                "We could not check the file, so we did not deliver it. Please try again later.",
            )
        )
        return await _fail(org_id, report_id, code, detail)
    except Exception:  # noqa: BLE001 - anything else is OUR fault
        log.exception("report %s crashed", report_id)
        return await _fail(
            org_id, report_id, "system_error", "Something went wrong on our side. Please try again."
        )


async def _fail(org_id: uuid.UUID, report_id: uuid.UUID, code: str, detail: str) -> str:
    async with tenant_session(org_id) as db:
        await db.execute(
            text(
                "UPDATE reports SET status='FAILED', error_code=:c, error_detail=:d, finished_at=now() WHERE id=:i AND status IN ('QUEUED','RUNNING')"
            ),
            {"c": code, "d": detail, "i": report_id},
        )
    return "FAILED"


@celery_app.task(name="docs.render_report", acks_late=True, max_retries=0)
def render_report_task(org_id: str, report_id: str) -> str:
    async def run() -> str:
        try:
            return await render_report(uuid.UUID(org_id), uuid.UUID(report_id))
        finally:
            await dispose_engines()

    return asyncio.run(run())
