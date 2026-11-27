"""Scanner benchmark gate (PROJECT_PLAN Phase 1 exit criterion: recorded recall/precision above the baseline).

Two suites: our own fixtures with embedded ground truth (regression gate, tuned by us) and the independent
GOV.UK accessibility-tool-audit pages (the honest number). Refresh the baseline deliberately, with a reviewed
diff: python -m a11y_web_audit.benchmark --write-baseline --markdown docs/benchmark.md"""

import asyncio
import json

import pytest
from a11y_web_audit.benchmark import BASELINE, ROOT, run_benchmark, run_govuk, to_markdown

BASE = json.loads(BASELINE.read_text())


@pytest.fixture(scope="module")
def results():
    return asyncio.run(run_benchmark()), asyncio.run(run_govuk())


def test_engine_versions_match_the_baseline(results):
    own, _ = results
    assert own["engine_versions"] == BASE["engine_versions"], (
        "engines changed: re-run the benchmark and review the new baseline"
    )


def test_own_fixtures_do_not_regress(results):
    own, _ = results
    assert (
        own["expected_defects"] == BASE["expected_defects"]
        and own["clean_elements"] == BASE["clean_elements"]
    ), "fixtures changed: refresh the baseline"
    for k, base in BASE["recall"].items():
        assert own["recall"][k] >= base - 0.02, (
            f"recall of {k} fell from {base} to {own['recall'][k]}"
        )
    assert own["false_positives_on_clean"]["merged"] <= BASE["false_positives_on_clean"]["merged"]
    assert own["unexpected_failures"]["count"] <= BASE["unexpected_failures"]
    assert own["strict_precision"] >= BASE["strict_precision"] - 0.02
    assert own["review_flagged"] >= BASE["review_flagged"]


def test_merging_beats_every_single_engine(results):
    own, gov = results
    best_single = max(own["recall"][e] for e in ("axe", "ibm", "htmlcs"))
    assert own["recall"]["merged"] > best_single
    assert gov["detected"] >= max(gov["by_engine"].values())


def test_independent_govuk_suite_does_not_regress(results):
    _, gov = results
    b = BASE["govuk"]
    assert gov["pages"] == b["pages"]
    assert gov["confirmed"] >= b["confirmed"] - 2, (
        f"confirmed detections fell from {b['confirmed']} to {gov['confirmed']}"
    )
    assert gov["automatable_confirmed"] >= b["automatable_confirmed"] - 2
    # the hand-review file must stay honest: it can only exclude pages that were actually detected
    assert gov["coincidental"] <= b["coincidental"] + 2


def test_every_flagged_failure_in_the_review_file_exists():
    review = json.loads((ROOT / "fixtures/benchmark/govuk-review.json").read_text())
    stems = [p.stem for p in (ROOT / "fixtures/benchmark/govuk/tests").glob("*.html")]
    for prefix in review["coincidental_prefixes"]:
        assert any(s.startswith(prefix) for s in stems), f"no test page starts with {prefix!r}"


def test_published_benchmark_document_is_current(results):
    own, gov = results
    assert (ROOT / "docs/benchmark.md").read_text() == to_markdown(own, gov), (
        "docs/benchmark.md is stale: python -m a11y_web_audit.benchmark --write-baseline --markdown docs/benchmark.md"
    )
