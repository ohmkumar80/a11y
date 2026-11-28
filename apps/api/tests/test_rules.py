"""Rule registry: data integrity, standards mapping, honest coverage summaries."""

import json
from pathlib import Path

import pytest
import yaml
from a11y_core.rules import Registry, get_registry, rules_dir

from .conftest import make_org
from .test_billing import auth

REG = get_registry()
ROOT = rules_dir().parent


def test_wcag_catalogue_is_complete():
    assert len(REG.criteria) == 87  # 86 in WCAG 2.2 + 4.1.1 (removed in 2.2)
    by_level = {
        lvl: len([c for c in REG.criteria.values() if c.level == lvl and not c.removed_in])
        for lvl in ("A", "AA", "AAA")
    }
    assert by_level == {
        "A": 31,
        "AA": 24,
        "AAA": 31,
    }  # WCAG 2.2: 32 A (incl. 4.1.1 removed), 24 AA, 30... verified below


def test_standards_scope_counts_match_the_published_specs():
    n = lambda s: len(REG.criteria_for(s))  # noqa: E731
    assert (n("WCAG_2_0_A"), n("WCAG_2_0_AA")) == (25, 38)
    assert (n("WCAG_2_1_A"), n("WCAG_2_1_AA")) == (30, 50)
    assert (n("WCAG_2_2_A"), n("WCAG_2_2_AA")) == (31, 55)
    assert n("WCAG_2_2_AAA") == 86


def test_4_1_1_parsing_is_obsolete_from_wcag_2_2():
    assert "4.1.1" in {c.id for c in REG.criteria_for("WCAG_2_1_AA")}
    assert "4.1.1" not in {c.id for c in REG.criteria_for("WCAG_2_2_AA")}


def test_new_2_2_criteria_only_in_2_2():
    new = {"2.4.11", "2.5.7", "2.5.8", "3.2.6", "3.3.7", "3.3.8"}
    ids21 = {c.id for c in REG.criteria_for("WCAG_2_1_AA")}
    ids22 = {c.id for c in REG.criteria_for("WCAG_2_2_AA")}
    assert not (new & ids21) and new <= ids22


@pytest.mark.parametrize(
    "std,base",
    [
        ("US_SECTION_508", "WCAG_2_0_AA"),
        ("US_ADA_TITLE_II", "WCAG_2_1_AA"),
        ("US_ADA_TITLE_III", "WCAG_2_1_AA"),
        ("EU_EAA_EN_301_549", "WCAG_2_1_AA"),
        ("IN_RPWD_GIGW_3", "WCAG_2_1_AA"),
        ("AU_DDA_AS_EN_301_549", "WCAG_2_2_AA"),
    ],
)
def test_legal_standards_map_to_the_documented_wcag_baseline(std, base):
    assert [c.id for c in REG.criteria_for(std)] == [c.id for c in REG.criteria_for(base)]


def test_legal_status_is_honest():
    s = REG.standards
    assert (
        s["US_ADA_TITLE_III"].legal_status == "benchmark"
    )  # no regulatory technical standard exists
    assert s["AU_DDA_AS_EN_301_549"].legal_status == "recommended_target"
    assert s["US_ADA_TITLE_II"].legal_status == "regulation"
    for st in s.values():
        if st.kind == "derived":
            assert st.citation, f"{st.id} needs a source citation"
    assert (
        REG.review["status"] == "draft" and REG.review["reviewed_by"] is None
    )  # no SME sign-off yet


def test_en_301_549_clause_numbers():
    assert REG.clause("EU_EAA_EN_301_549", "1.4.3") == "9.1.4.3"
    assert REG.clause("US_ADA_TITLE_II", "1.4.3") == "WCAG 1.4.3"


def test_canonical_rules_reference_only_rules_that_exist_in_the_pinned_engines():
    cat = json.loads((ROOT / "rules/engine-catalog.json").read_text())
    for cr in REG.canonical.values():
        for ref in cr.axe:
            assert ref.id in cat["axe"], f"{cr.id}: axe has no rule {ref.id}"
        for ref in cr.ibm:
            assert ref.id in cat["ibm"], f"{cr.id}: IBM has no rule {ref.id}"


def test_canonical_sc_agrees_with_what_the_engines_say():
    """Our SC for a canonical rule must include the SC the engines themselves attach to its axe/IBM
    rules (we may add more, e.g. 4.1.2 for name rules, but never contradict them)."""
    cat = json.loads((ROOT / "rules/engine-catalog.json").read_text())
    for cr in REG.canonical.values():
        if cr.best_practice:
            continue
        engine_sc = {s for ref in cr.axe for s in cat["axe"][ref.id]} | {
            s for ref in cr.ibm for s in cat["ibm"][ref.id]["sc"]
        }
        assert engine_sc <= set(cr.sc) | {"4.1.2", "1.3.1", "2.4.4"}, (
            cr.id,
            engine_sc - set(cr.sc),
        )


def test_engine_catalog_matches_the_pinned_bundles():
    versions = ROOT / "packages/engine-bundles/dist/versions.json"
    if not versions.exists():
        pytest.skip("engine bundles not built")
    built = {k: v["version"] for k, v in json.loads(versions.read_text()).items()}
    assert REG.engine_versions == built, (
        "run workers/web_audit/scripts/gen_engine_catalog.py after upgrading engines"
    )


def test_lookup_across_engines_and_tag_filters():
    g = REG.canonical_for
    assert (
        g("axe", "image-alt").id
        == g("ibm", "img_alt_valid").id
        == g("htmlcs", "H37").id
        == "image-alt"
    )
    assert g("htmlcs", "H91.Button.Name").id == "button-name"
    assert g("ibm", "input_label_exists", "button").id == "button-name"
    assert g("ibm", "input_label_exists", "input").id == "form-field-label"
    assert g("ibm", "input_label_exists", "div").id == "widget-name"
    assert g("ibm", "input_label_exists", None) is None  # ambiguous without an element tag
    assert g("axe", "some-new-rule") is None


def test_validation_rejects_bad_data(tmp_path):
    def build(mutate):
        for n in ("wcag.yaml", "standards.yaml", "canonical.yaml", "engine-catalog.json"):
            (tmp_path / n).write_text((rules_dir() / n).read_text())
        mutate(tmp_path)
        return Registry(tmp_path)

    def dup(p: Path):
        c = yaml.safe_load((p / "canonical.yaml").read_text())
        c["rules"].append({**c["rules"][0], "id": "image-alt-2"})
        (p / "canonical.yaml").write_text(yaml.safe_dump(c))

    def bad_sc(p: Path):
        c = yaml.safe_load((p / "canonical.yaml").read_text())
        c["rules"][0]["sc"] = ["9.9.9"]
        (p / "canonical.yaml").write_text(yaml.safe_dump(c))

    def bad_base(p: Path):
        s = yaml.safe_load((p / "standards.yaml").read_text())
        s["standards"][-1]["base"] = "NOPE"
        (p / "standards.yaml").write_text(yaml.safe_dump(s))

    with pytest.raises(ValueError, match="mapped to both"):
        build(dup)
    with pytest.raises(ValueError, match="unknown criterion"):
        build(bad_sc)
    with pytest.raises(ValueError, match="base"):
        build(bad_base)
    build(lambda p: None)  # the real data is valid


def test_summary_is_coverage_not_compliance():
    findings = [
        {"sc": ["1.1.1"], "kind": "violation"},
        {"sc": ["1.4.3"], "kind": "needs_review"},
        {"sc": ["1.1.1"], "kind": "needs_review"},
        {"sc": [], "kind": "best_practice"},
        {"sc": ["2.5.8"], "kind": "violation"},  # 2.2-only: outside WCAG 2.1
    ]
    s21 = REG.summarise("WCAG_2_1_AA", findings)
    assert s21.failed == ["1.1.1"] and s21.needs_review == ["1.4.3"]
    assert "2.5.8" not in s21.failed  # switching standard re-filters existing data
    s22 = REG.summarise("WCAG_2_2_AA", findings)
    assert s22.failed == ["1.1.1", "2.5.8"]
    tested, total = s22.automated_coverage
    assert total == 55 and 0 < tested < total  # some criteria can never be tested by automation
    # every criterion is in exactly one bucket
    all_ids = s22.failed + s22.needs_review + s22.no_issues_found + s22.not_tested
    assert sorted(all_ids) == sorted(c.id for c in REG.criteria_for("WCAG_2_2_AA"))
    assert "1.2.5" in s22.not_tested  # audio description quality: no automation exists


def test_clean_scan_never_means_conformant():
    s = REG.summarise("WCAG_2_1_AA", [])
    assert s.failed == [] and len(s.not_tested) > 0  # a clean scan still leaves criteria untested
    assert "no_issues_found" in s.__dataclass_fields__  # named "no issues found", not "passed"


async def test_standards_api(client):
    org, user, _ = await make_org()
    h = auth(org, user)
    assert (await client.get("/standards")).status_code == 401
    r = (await client.get("/standards", headers=h)).json()
    assert r["review"]["status"] == "draft"
    ids = {s["id"]: s for s in r["standards"]}
    assert (
        ids["WCAG_2_2_AA"]["criteria_count"] == 55
        and ids["US_ADA_TITLE_III"]["legal_status"] == "benchmark"
    )
    crit = (await client.get("/standards/EU_EAA_EN_301_549/criteria", headers=h)).json()
    assert crit[0] == {
        "id": "1.1.1",
        "name": "Non-text Content",
        "level": "A",
        "clause": "9.1.1.1",
        "automated": True,
    }
    assert (await client.get("/standards/NOPE/criteria", headers=h)).status_code == 404
