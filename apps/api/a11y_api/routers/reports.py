"""Generated reports (audit PDF / DOCX / CSV) and the VPAT draft -> sign-off -> export flow.

Files are rendered by the docs worker and only become downloadable when their accessibility gate passed.
The VPAT cannot be exported before a person signs it off (PROJECT_PLAN 1.7)."""

import json
import re
import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit

from a11y_core.celery_app import celery_app
from a11y_core.db import tenant_session
from a11y_core.models import AuditLog
from a11y_core.rules import get_registry
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from ..deps import current_principal, require_company_admin
from ..security import Principal

router = APIRouter(tags=["reports"])
AUDIT_KINDS = ("audit_pdf", "audit_docx", "audit_csv")
MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "csv": "text/csv; charset=utf-8",
}
MAX_ACTIVE = 5
SIGNOFF_TEXT = (
    "I have reviewed each conformance level and remark in this document and confirm that they reflect my own evaluation. "
    "I understand that automated tests alone cannot establish conformance."
)


def _problem(http_status: int, detail: str, field: str | None = None, **extra) -> HTTPException:
    return HTTPException(http_status, detail={"detail": detail, "field": field, **extra})


def _ext(kind: str) -> str:
    return kind.split("_")[1]


def _report_json(r) -> dict:
    return {
        "id": str(r.id),
        "scan_id": str(r.scan_id),
        "kind": r.kind,
        "standard": r.standard,
        "status": r.status,
        "error_code": r.error_code,
        "error_detail": r.error_detail,
        "size_bytes": r.size_bytes,
        "template_version": r.template_version,
        "validation": r.validation,
        "created_at": r.created_at,
        "finished_at": r.finished_at,
        "vpat_id": str(r.vpat_id) if r.vpat_id else None,
    }


async def _scan(db, scan_id: uuid.UUID):
    s = (
        await db.execute(
            text("SELECT id, status, standards, start_url FROM scan_jobs WHERE id=:i"),
            {"i": scan_id},
        )
    ).first()
    if s is None:
        raise _problem(404, "We could not find that scan.")
    return s


async def _enqueue(org_id: uuid.UUID, report_id: uuid.UUID) -> None:
    try:
        celery_app.send_task("docs.render_report", args=[str(org_id), str(report_id)], queue="docs")
    except Exception:  # noqa: BLE001
        async with tenant_session(org_id) as db:
            await db.execute(
                text(
                    "UPDATE reports SET status='FAILED', error_code='queue_unavailable', error_detail='We could not start the report. Try again shortly.', finished_at=now() WHERE id=:i"
                ),
                {"i": report_id},
            )
        raise _problem(
            503,
            "We could not start the report right now. Please try again shortly.",
            code="queue_unavailable",
        ) from None


async def _create_report(
    p: Principal,
    scan_id: uuid.UUID,
    kind: str,
    standard: str,
    vpat_id: uuid.UUID | None,
    *,
    regenerate: bool = False,
) -> tuple[uuid.UUID, bool]:
    async with tenant_session(p.org_id) as db:
        if not regenerate:
            same = (
                await db.execute(
                    text(
                        "SELECT id FROM reports WHERE scan_id=:s AND kind=:k AND standard=:st AND vpat_id IS NOT DISTINCT FROM :v AND status IN ('QUEUED','RUNNING','READY') "
                        "ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"s": scan_id, "k": kind, "st": standard, "v": vpat_id},
                )
            ).first()
            if same:
                return same.id, True
        active = (
            await db.execute(
                text("SELECT count(*) FROM reports WHERE status IN ('QUEUED','RUNNING')")
            )
        ).scalar_one()
        if active >= MAX_ACTIVE:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "detail": "Several reports are still being prepared. Wait a moment.",
                    "code": "too_many_reports",
                },
                headers={"Retry-After": "20"},
            )
        rid = uuid.uuid4()
        await db.execute(
            text(
                "INSERT INTO reports (id, organization_id, scan_id, vpat_id, kind, standard, created_by) VALUES (:i, :o, :s, :v, :k, :st, :u)"
            ),
            {
                "i": rid,
                "o": p.org_id,
                "s": scan_id,
                "v": vpat_id,
                "k": kind,
                "st": standard,
                "u": p.user_id,
            },
        )
    await _enqueue(p.org_id, rid)
    return rid, False


class ReportIn(BaseModel):
    kind: str = Field(pattern="^(audit_pdf|audit_docx|audit_csv)$")
    standard: str | None = Field(None, max_length=40)
    regenerate: bool = False


@router.post("/scans/{scan_id}/reports", status_code=status.HTTP_202_ACCEPTED)
async def create_report(
    scan_id: uuid.UUID, body: ReportIn, p: Principal = Depends(current_principal)
):
    reg = get_registry()
    async with tenant_session(p.org_id) as db:
        s = await _scan(db, scan_id)
    if s.status != "SUCCEEDED":
        raise _problem(
            409,
            "Reports can be created once the scan has finished successfully.",
            code="scan_not_finished",
        )
    standard = body.standard or (s.standards[0] if s.standards else "WCAG_2_2_AA")
    if standard not in reg.standards:
        raise _problem(422, f"Unknown standard {standard}.", "standard")
    rid, reused = await _create_report(
        p, scan_id, body.kind, standard, None, regenerate=body.regenerate
    )
    return {"id": str(rid), "status": "QUEUED", "reused": reused}


@router.get("/scans/{scan_id}/reports")
async def list_reports(scan_id: uuid.UUID, p: Principal = Depends(current_principal)):
    async with tenant_session(p.org_id) as db:
        await _scan(db, scan_id)
        rows = (
            await db.execute(
                text(
                    "SELECT id, scan_id, vpat_id, kind, standard, status, error_code, error_detail, size_bytes, template_version, validation, created_at, finished_at FROM reports WHERE scan_id=:s ORDER BY created_at DESC LIMIT 50"
                ),
                {"s": scan_id},
            )
        ).all()
    return [_report_json(r) for r in rows]


@router.get("/reports/{report_id}")
async def get_report(report_id: uuid.UUID, p: Principal = Depends(current_principal)):
    async with tenant_session(p.org_id) as db:
        r = (
            await db.execute(
                text(
                    "SELECT id, scan_id, vpat_id, kind, standard, status, error_code, error_detail, size_bytes, template_version, validation, created_at, finished_at FROM reports WHERE id=:i"
                ),
                {"i": report_id},
            )
        ).first()
    if r is None:
        raise _problem(404, "We could not find that report.")
    return _report_json(r)


@router.get("/reports/{report_id}/download")
async def download(report_id: uuid.UUID, p: Principal = Depends(current_principal)):
    async with tenant_session(p.org_id) as db:
        r = (
            await db.execute(
                text(
                    "SELECT r.kind, r.standard, r.status, r.content, r.created_at, s.start_url FROM reports r JOIN scan_jobs s ON s.id = r.scan_id WHERE r.id=:i"
                ),
                {"i": report_id},
            )
        ).first()
    if r is None:
        raise _problem(404, "We could not find that report.")
    if r.status != "READY" or r.content is None:
        raise _problem(409, "This report is not ready to download.", code="report_not_ready")
    host = re.sub(r"[^a-z0-9.-]", "-", (urlsplit(r.start_url).hostname or "site").lower())
    base = "vpat" if r.kind.startswith("vpat") else "audit"
    name = f"a11y-{base}-{host}-{r.created_at:%Y-%m-%d}.{_ext(r.kind)}"
    return Response(
        bytes(r.content),
        media_type=MIME[_ext(r.kind)],
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


# --- VPAT -----------------------------------------------------------------------------------------------------


class VpatCreate(BaseModel):
    standard: str = Field("WCAG_2_2_AA", max_length=40)
    edition: str = Field("WCAG", pattern="^(WCAG|508|EU|INT)$")


class CriterionEdit(BaseModel):
    id: str = Field(max_length=10)
    conformance: str | None = None
    remarks: str | None = Field(None, max_length=4000)


class ProductEdit(BaseModel):
    name: str | None = Field(None, max_length=200)
    version: str | None = Field(None, max_length=100)
    description: str | None = Field(None, max_length=2000)
    contact: str | None = Field(None, max_length=300)
    notes: str | None = Field(None, max_length=2000)


class VpatPatch(BaseModel):
    product: ProductEdit | None = None
    criteria: list[CriterionEdit] = Field(default_factory=list, max_length=100)


class SignoffIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    role: str = Field(min_length=2, max_length=200)
    confirm: bool


class ExportIn(BaseModel):
    format: str = Field(pattern="^(pdf|docx)$")
    regenerate: bool = False


def _vpat_json(v, problems: list[str]) -> dict:
    from a11y_core.vpat import LEVELS  # noqa: PLC0415

    crit = v.criteria
    return {
        "id": str(v.id),
        "scan_id": str(v.scan_id),
        "standard": v.standard,
        "edition": v.edition,
        "status": v.status,
        "product": v.product,
        "criteria": crit,
        "levels": list(LEVELS),
        "mapping_review": v.mapping_review,
        "signoff": v.signoff,
        "not_evaluated": sum(c["conformance"] == "Not Evaluated" for c in crit),
        "total": len(crit),
        "problems": problems,
        "signoff_text": SIGNOFF_TEXT,
        "updated_at": v.updated_at,
    }


async def _load_vpat(db, vpat_id: uuid.UUID, *, lock: bool = False):
    q = (
        "SELECT * FROM vpat_reports WHERE id=:i FOR UPDATE"
        if lock
        else "SELECT * FROM vpat_reports WHERE id=:i"
    )
    v = (await db.execute(text(q), {"i": vpat_id})).first()
    if v is None:
        raise _problem(404, "We could not find that VPAT.")
    return v


def _problems(v) -> list[str]:
    from a11y_core.vpat import VpatCriterion, validate_edits  # noqa: PLC0415

    return validate_edits([VpatCriterion(**c) for c in v.criteria])


@router.post("/scans/{scan_id}/vpat", status_code=status.HTTP_201_CREATED)
async def create_vpat(
    scan_id: uuid.UUID, body: VpatCreate, p: Principal = Depends(require_company_admin)
):
    from a11y_core.vpat import create_draft  # noqa: PLC0415

    if body.standard not in get_registry().standards:
        raise _problem(422, f"Unknown standard {body.standard}.", "standard")
    async with tenant_session(p.org_id) as db:
        s = await _scan(db, scan_id)
        if s.status != "SUCCEEDED":
            raise _problem(
                409,
                "A VPAT can be drafted once the scan has finished successfully.",
                code="scan_not_finished",
            )
        vid = await create_draft(
            db,
            p.org_id,
            scan_id,
            body.standard,
            body.edition,
            p.user_id,
            product_name=urlsplit(s.start_url).hostname or s.start_url,
        )
    return {"id": str(vid)}


@router.get("/vpats/{vpat_id}")
async def get_vpat(vpat_id: uuid.UUID, p: Principal = Depends(current_principal)):
    async with tenant_session(p.org_id) as db:
        v = await _load_vpat(db, vpat_id)
    return _vpat_json(v, _problems(v))


@router.patch("/vpats/{vpat_id}")
async def patch_vpat(
    vpat_id: uuid.UUID, body: VpatPatch, p: Principal = Depends(require_company_admin)
):
    from a11y_core.vpat import LEVELS, NEEDS_REMARKS  # noqa: PLC0415

    async with tenant_session(p.org_id) as db:
        v = await _load_vpat(db, vpat_id, lock=True)
        if v.status == "SIGNED_OFF":
            raise _problem(
                409, "This VPAT is signed off. Reopen it to change it.", code="vpat_locked"
            )
        crit = [dict(c) for c in v.criteria]
        by_id = {c["id"]: c for c in crit}
        for e in body.criteria:
            c = by_id.get(e.id)
            if c is None:
                raise _problem(422, f"{e.id} is not a criterion in this standard.", "criteria")
            if e.conformance is not None:
                if e.conformance not in LEVELS:
                    raise _problem(
                        422, f"'{e.conformance}' is not a conformance level.", "criteria"
                    )
                c["conformance"] = e.conformance
            if e.remarks is not None:
                c["remarks"] = e.remarks.strip()
            c["source"] = "manual"
            if c["conformance"] in NEEDS_REMARKS and not c["remarks"].strip():
                raise _problem(
                    422,
                    f"{c['clause']} {c['name']}: explain why it is '{c['conformance']}'.",
                    "criteria",
                )
        product = {
            **(v.product or {}),
            **{
                k: x
                for k, x in (
                    body.product.model_dump(exclude_none=True) if body.product else {}
                ).items()
            },
        }
        await db.execute(
            text(
                "UPDATE vpat_reports SET criteria=CAST(:c AS jsonb), product=CAST(:p AS jsonb), updated_at=now() WHERE id=:i"
            ),
            {"c": json.dumps(crit), "p": json.dumps(product), "i": vpat_id},
        )
        v = await _load_vpat(db, vpat_id)
    return _vpat_json(v, _problems(v))


@router.post("/vpats/{vpat_id}/signoff")
async def signoff(
    vpat_id: uuid.UUID, body: SignoffIn, p: Principal = Depends(require_company_admin)
):
    if not body.confirm:
        raise _problem(422, "Confirm that you have reviewed the document.", "confirm")
    async with tenant_session(p.org_id) as db:
        v = await _load_vpat(db, vpat_id, lock=True)
        if v.status == "SIGNED_OFF":
            raise _problem(409, "This VPAT is already signed off.", code="vpat_locked")
        if problems := _problems(v):
            raise _problem(
                422,
                "Fix these before signing off: "
                + " ".join(problems[:3])
                + (f" (and {len(problems) - 3} more)" if len(problems) > 3 else ""),
                "criteria",
                problems=problems,
            )
        so = {
            "name": body.name.strip(),
            "role": body.role.strip(),
            "statement": SIGNOFF_TEXT,
            "user_id": str(p.user_id),
            "signed_at": datetime.now(UTC).isoformat(),
        }
        await db.execute(
            text(
                "UPDATE vpat_reports SET status='SIGNED_OFF', signoff=CAST(:s AS jsonb), updated_at=now() WHERE id=:i"
            ),
            {"s": json.dumps(so), "i": vpat_id},
        )
        db.add(
            AuditLog(
                organization_id=p.org_id,
                actor_user_id=p.user_id,
                action="vpat.signed_off",
                detail={"vpat_id": str(vpat_id), "name": so["name"], "role": so["role"]},
            )
        )
        v = await _load_vpat(db, vpat_id)
    return _vpat_json(v, [])


@router.post("/vpats/{vpat_id}/reopen")
async def reopen(vpat_id: uuid.UUID, p: Principal = Depends(require_company_admin)):
    async with tenant_session(p.org_id) as db:
        v = await _load_vpat(db, vpat_id, lock=True)
        if v.status == "DRAFT":
            return _vpat_json(v, _problems(v))
        await db.execute(
            text(
                "UPDATE vpat_reports SET status='DRAFT', signoff=NULL, updated_at=now() WHERE id=:i"
            ),
            {"i": vpat_id},
        )
        db.add(
            AuditLog(
                organization_id=p.org_id,
                actor_user_id=p.user_id,
                action="vpat.reopened",
                detail={"vpat_id": str(vpat_id)},
            )
        )
        v = await _load_vpat(db, vpat_id)
    return _vpat_json(v, _problems(v))


@router.post("/vpats/{vpat_id}/export", status_code=status.HTTP_202_ACCEPTED)
async def export_vpat(
    vpat_id: uuid.UUID, body: ExportIn, p: Principal = Depends(require_company_admin)
):
    async with tenant_session(p.org_id) as db:
        v = await _load_vpat(db, vpat_id)
    if v.status != "SIGNED_OFF":
        raise _problem(
            409,
            "A person must review and sign off the VPAT before it can be exported.",
            code="vpat_not_signed_off",
        )
    rid, reused = await _create_report(
        p, v.scan_id, f"vpat_{body.format}", v.standard, vpat_id, regenerate=body.regenerate
    )
    return {"id": str(rid), "status": "QUEUED", "reused": reused}
