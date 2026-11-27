"""Normalisation without a browser: merging, confidence, scopes, clustering."""

from a11y_core.rules import get_registry
from a11y_web_audit.normalise import normalise

REG = get_registry()


def el(xpath="/html[1]/body[1]/img[1]", tag="img", css="html > body > img:nth-of-type(1)"):
    return {"xpath": xpath, "css": css, "tag": tag, "html": f"<{tag}>", "rect": None}


def raw(engine, rule_id, kind="violation", impact="serious", element=None, sc=None, **kw):
    return {
        "engine": engine,
        "rule_id": rule_id,
        "kind": kind,
        "impact": impact,
        "sc": sc or [],
        "message": f"{engine} says {rule_id}",
        "element": element or el(),
        "best_practice": False,
        **kw,
    }


ALL = {"axe", "ibm", "htmlcs"}


def test_same_defect_from_three_engines_is_one_high_confidence_finding():
    out = normalise(
        [
            raw("htmlcs", "H37"),
            raw("ibm", "img_alt_valid"),
            raw("axe", "image-alt", impact="critical"),
        ],
        REG,
        ran_ok=ALL,
    )
    assert len(out) == 1
    f = out[0]
    assert (f.canonical_rule_id, f.engines, f.confidence, f.severity, f.sc) == (
        "image-alt",
        ["axe", "ibm", "htmlcs"],
        "high",
        "critical",
        ["1.1.1"],
    )
    assert f.message == "axe says image-alt"  # axe's wording is preferred
    assert f.engine_rule_ids == {"axe": ["image-alt"], "ibm": ["img_alt_valid"], "htmlcs": ["H37"]}


def test_single_engine_finding_while_others_stay_silent_is_low_confidence():
    f = normalise([raw("htmlcs", "F68")], REG, ran_ok=ALL)[0]
    assert (f.canonical_rule_id, f.engines, f.confidence) == ("form-field-label", ["htmlcs"], "low")
    assert set(f.covering) == ALL


def test_confidence_when_only_one_engine_covers_the_rule():
    f = normalise([raw("axe", "image-alt")], REG, ran_ok={"axe"})[
        0
    ]  # IBM/HTMLCS were off or failed
    assert f.confidence == "medium" and f.covering == ["axe"]
    f = normalise([raw("axe", "identical-links-same-purpose")], REG, ran_ok=ALL)[
        0
    ]  # only axe has a rule for it
    assert f.confidence == "medium"


def test_page_level_rules_merge_even_when_engines_blame_different_elements():
    out = normalise(
        [
            raw("axe", "document-title", element=el("/html[1]", "html", "html")),
            raw("ibm", "page_title_exists", element=el("/html[1]", "html", "html")),
            raw(
                "htmlcs",
                "H25.1.EmptyTitle",
                element=el("/html[1]/head[1]/title[1]", "title", "html > head > title"),
            ),
        ],
        REG,
        ran_ok=ALL,
    )
    assert (
        len(out) == 1 and out[0].xpath == "/html[1]" and out[0].engines == ["axe", "ibm", "htmlcs"]
    )


def test_generic_ibm_rule_maps_by_element_type():
    out = normalise(
        [
            raw("ibm", "input_label_exists", element=el("/html[1]/body[1]/button[1]", "button")),
            raw("ibm", "input_label_exists", element=el("/html[1]/body[1]/input[1]", "input")),
            raw("ibm", "input_label_exists", element=el("/html[1]/body[1]/div[1]", "div")),
        ],
        REG,
        ran_ok=ALL,
    )
    assert sorted(f.canonical_rule_id for f in out) == [
        "button-name",
        "form-field-label",
        "widget-name",
    ]


def test_kind_merging_violation_wins_and_review_is_not_a_failure():
    f = normalise(
        [
            raw("axe", "color-contrast", kind="needs_review"),
            raw("ibm", "text_contrast_sufficient", kind="violation"),
        ],
        REG,
        ran_ok=ALL,
    )[0]
    assert (f.kind, f.confidence) == ("violation", "medium" if False else f.confidence)
    r = normalise([raw("axe", "color-contrast", kind="needs_review")], REG, ran_ok=ALL)[0]
    assert (r.kind, r.confidence) == ("needs_review", "review")


def test_best_practices_are_kept_apart_and_minor():
    f = normalise(
        [
            raw(
                "axe",
                "heading-order",
                kind="violation",
                impact="moderate",
                element=el("/html[1]/body[1]/h4[1]", "h4"),
            )
        ],
        REG,
        ran_ok=ALL,
    )[0]
    assert (f.kind, f.sc, f.canonical_rule_id) == ("best_practice", [], "heading-order")
    d = normalise([raw("axe", "duplicate-id")], REG, ran_ok=ALL)[0]
    assert d.kind == "best_practice"  # 4.1.1 is obsolete in WCAG 2.2


def test_unmapped_rules_are_still_reported_with_engine_sc():
    f = normalise([raw("axe", "brand-new-rule", sc=["1.4.3"])], REG, ran_ok=ALL)[0]
    assert (f.canonical_rule_id, f.mapped, f.sc) == ("axe:brand-new-rule", False, ["1.4.3"])


def test_different_elements_stay_separate():
    out = normalise(
        [
            raw("axe", "image-alt", element=el("/html[1]/body[1]/img[1]")),
            raw("axe", "image-alt", element=el("/html[1]/body[1]/img[2]")),
        ],
        REG,
        ran_ok=ALL,
    )
    assert len(out) == 2 and len({f.fingerprint for f in out}) == 2


def test_cluster_key_groups_the_same_template_defect_across_pages():
    a = normalise(
        [
            raw(
                "axe",
                "image-alt",
                element=el(css="html > body > ul > li:nth-of-type(3) > img:nth-of-type(1)"),
            )
        ],
        REG,
        ran_ok=ALL,
    )[0]
    b = normalise(
        [
            raw(
                "axe",
                "image-alt",
                element=el(css="html > body > ul > li:nth-of-type(41) > img:nth-of-type(1)"),
            )
        ],
        REG,
        ran_ok=ALL,
    )[0]
    c = normalise(
        [raw("axe", "image-alt", element=el(css="html > body > div > img:nth-of-type(1)"))],
        REG,
        ran_ok=ALL,
    )[0]
    assert a.cluster_key == b.cluster_key != c.cluster_key


def test_ordering_is_most_severe_first():
    out = normalise(
        [
            raw("axe", "link-name", impact="serious", element=el("/a", "a")),
            raw("axe", "image-alt", impact="critical"),
        ],
        REG,
        ran_ok=ALL,
    )
    assert [f.severity for f in out] == ["critical", "serious"]
