"""Sample data for template tests, golden renders and the admin template preview."""

from __future__ import annotations

from .data import (
    AuditReportData,
    ClusterRow,
    CriteriaBuckets,
    CriterionRef,
    Example,
    PageRow,
    StandardInfo,
    build_narrative,
)


def _c(i: str, n: str, lvl: str) -> CriterionRef:
    return CriterionRef(id=i, name=n, level=lvl, clause=f"WCAG {i}")


def sample_audit_data(*, hostile: bool = False) -> AuditReportData:
    evil = (
        '<img src=x onerror="alert(1)"><script>alert(2)</script>'
        if hostile
        else '<img src="logo.png">'
    )
    d = AuditReportData(
        organization="Example Ltd" if not hostile else "Évil <b>Corp</b> & Sons",
        site="https://www.example.com/",
        site_host="www.example.com",
        generated_on="27 November 2026",
        scanned_on="26 November 2026",
        standard=StandardInfo(
            id="WCAG_2_2_AA",
            label="WCAG 2.2 Level AA",
            legal_status="reference",
            legal_label="A reference standard",
            citation=None,
            notes=None,
            mapping_review="draft",
        ),
        engine_versions={"axe": "4.14.1", "ibm": "4.0.35", "htmlcs": "2.5.1"},
        rules_version="2026-11-27.1",
        mode="crawl",
        pages_scanned=3,
        severity_counts={"critical": 4, "serious": 2, "moderate": 1, "minor": 0},
        failures=7,
        needs_review=5,
        best_practices=3,
        criteria=CriteriaBuckets(
            failed=[_c("1.1.1", "Non-text Content", "A"), _c("4.1.2", "Name, Role, Value", "A")],
            needs_review=[_c("1.4.3", "Contrast (Minimum)", "AA")],
            no_issues_found=[_c("3.1.1", "Language of Page", "A")],
            not_tested=[_c("1.2.5", "Audio Description (Prerecorded)", "AA")],
            tested=30,
            total=55,
        ),
        clusters=[
            ClusterRow(
                rule="image-alt",
                title="Images need a text alternative",
                criteria=[_c("1.1.1", "Non-text Content", "A")],
                severity="critical",
                kind="violation",
                occurrences=4,
                pages=2,
                confidence="High",
                agreement="3 of 3 engines",
                examples=[
                    Example(
                        page="https://www.example.com/",
                        css="main > img",
                        html=evil,
                        message="Element does not have an alt attribute",
                    ),
                    Example(
                        page="https://www.example.com/about",
                        css="footer img",
                        html='<img src="x.png">',
                        message="",
                    ),
                ],
            ),
            ClusterRow(
                rule="button-name",
                title="Buttons need discernible text",
                criteria=[_c("4.1.2", "Name, Role, Value", "A")],
                severity="serious",
                kind="violation",
                occurrences=2,
                pages=1,
                confidence="Medium",
                agreement="1 of 1 engines",
                examples=[
                    Example(
                        page="https://www.example.com/",
                        css="form > button",
                        html="<button></button>",
                        message="தமிழ் செய்தி: பொத்தானுக்கு பெயர் இல்லை",
                    )
                ],
            ),
            ClusterRow(
                rule="color-contrast",
                title="=cmd|' /C calc'!A0 Text needs sufficient contrast"
                if hostile
                else "Text needs sufficient contrast",
                criteria=[_c("1.4.3", "Contrast (Minimum)", "AA")],
                severity="moderate",
                kind="violation",
                occurrences=1,
                pages=1,
                confidence="High",
                agreement="3 of 3 engines",
                examples=[
                    Example(
                        page="https://www.example.com/",
                        css="p.lead",
                        html='<p class="lead">Light text</p>',
                        message="",
                    )
                ],
            ),
        ],
        clusters_total=3,
        pages=[
            PageRow(url="https://www.example.com/", result="Scanned"),
            PageRow(url="https://www.example.com/about", result="Scanned"),
            PageRow(
                url="https://www.example.com/private",
                result="Skipped: the site's robots.txt asks scanners not to visit this page.",
            ),
        ],
        narrative=[],
    )
    d.narrative = build_narrative(d)
    return d
