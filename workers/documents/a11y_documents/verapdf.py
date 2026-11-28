"""PDF/UA-1 validation with veraPDF. This is the GATE before a generated PDF may be downloaded
(PROJECT_PLAN 2.5): a failing file is never delivered.

Runner lookup: $VERAPDF_BIN, then `verapdf` on PATH, then /opt/verapdf/verapdf (the docs-worker image),
then the `ghcr.io/verapdf/cli` Docker image (developer machines, CI).

Passing veraPDF is NECESSARY, not sufficient: it checks the machine-verifiable PDF/UA rules, not whether
the reading order, alt text or headings make sense (those are checked by tests on our templates and by the
manual release checklist)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

DOCKER_IMAGE = "ghcr.io/verapdf/cli"
TIMEOUT_S = 120


class VeraPdfUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class FailedRule:
    clause: str
    test: int
    failed_checks: int
    description: str


@dataclass(frozen=True)
class PdfUaResult:
    compliant: bool
    passed_rules: int
    failed: list[FailedRule] = field(default_factory=list)
    tool_version: str = ""

    def summary(self) -> str:
        if self.compliant:
            return f"PDF/UA-1: passed {self.passed_rules} rules"
        return "PDF/UA-1 failed: " + "; ".join(
            f"{r.clause}#{r.test} x{r.failed_checks}" for r in self.failed
        )


def _local_binary() -> str | None:
    for cand in (os.environ.get("VERAPDF_BIN"), shutil.which("verapdf"), "/opt/verapdf/verapdf"):
        if cand and Path(cand).exists():
            return cand
    return None


def runner_available() -> bool:
    return _local_binary() is not None or (
        shutil.which("docker") is not None and _docker_image_ready()
    )


def _docker_image_ready() -> bool:
    r = subprocess.run(
        ["docker", "image", "inspect", DOCKER_IMAGE], capture_output=True, check=False
    )  # noqa: S603, S607
    return r.returncode == 0


def validate_pdf_ua(pdf: bytes) -> PdfUaResult:
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "file.pdf"
        path.write_bytes(pdf)
        local = _local_binary()
        if local:
            cmd = [local, "--flavour", "ua1", "--format", "json", str(path)]
        elif shutil.which("docker"):
            os.chmod(d, 0o755)  # the container user must be able to read it
            path.chmod(0o644)
            cmd = [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{d}:/data:ro",
                DOCKER_IMAGE,
                "--flavour",
                "ua1",
                "--format",
                "json",
                "/data/file.pdf",
            ]
        else:
            raise VeraPdfUnavailable("veraPDF is not installed and Docker is not available")
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S, check=False)  # noqa: S603
        except subprocess.TimeoutExpired:
            raise VeraPdfUnavailable("veraPDF timed out") from None
    try:
        report = json.loads(r.stdout)["report"]
        job = report["jobs"][0]
        vr = job["validationResult"]
        vr = vr[0] if isinstance(vr, list) else vr
    except (ValueError, KeyError, IndexError):
        raise VeraPdfUnavailable(f"veraPDF gave no usable result (exit {r.returncode})") from None
    details = vr["details"]
    return PdfUaResult(
        compliant=bool(vr["compliant"]),
        passed_rules=int(details["passedRules"]),
        failed=[
            FailedRule(s["clause"], int(s["testNumber"]), int(s["failedChecks"]), s["description"])
            for s in details.get("ruleSummaries", [])
        ],
        tool_version=str(
            report.get("buildInformation", {}).get("releaseDetails", [{}])[0].get("version", "")
        ),
    )
