# Scanner benchmark

Engines: axe 4.14.1, ibm 4.0.35, htmlcs 2.5.1. Rules 2026-11-27.1. 33 fixture pages, 60 planted defects, 55 known-good elements. Ground truth is embedded in `fixtures/benchmark/cases`.

| | Planted defects found | Recall | False failures on known-good elements |
|---|---|---|---|
| **All three engines merged** | 60 of 60 | 100% | 0 |
| Merged, high confidence only | 46 of 60 | 77% | n/a |
| axe-core alone | 53 of 60 | 88% | 0 |
| IBM Equal Access alone | 47 of 60 | 78% | 1 |
| HTML_CodeSniffer alone | 26 of 60 | 43% | 0 |

Strict precision (planted defects found / those + false failures + unexpected failures): **100%**. Unexpected failures (nobody planted them; each is reviewed): 0. Defects the merged result only flagged as 'needs review': 0. Items no machine can decide (should be flagged for human review): 1 of 1 flagged.

## By rule

| Rule | Planted | Merged | axe | IBM | HTMLCS |
|---|---|---|---|---|---|
| area-alt | 1 | 1 | 1 | 1 | 1 |
| aria-attributes | 3 | 3 | 3 | 3 | 0 |
| aria-hidden-focus | 2 | 2 | 2 | 2 | 0 |
| aria-required-structure | 2 | 2 | 2 | 2 | 0 |
| aria-roles | 2 | 2 | 2 | 2 | 0 |
| autocomplete-valid | 2 | 2 | 2 | 2 | 0 |
| button-name | 3 | 3 | 3 | 3 | 3 |
| color-contrast | 3 | 3 | 3 | 3 | 3 |
| document-title | 1 | 1 | 1 | 1 | 1 |
| duplicate-id | 1 | 1 | 0 | 0 | 1 |
| empty-heading | 2 | 2 | 2 | 2 | 2 |
| form-field-label | 4 | 4 | 3 | 3 | 4 |
| frame-title | 1 | 1 | 1 | 1 | 1 |
| heading-order | 1 | 1 | 1 | 0 | 0 |
| html-lang | 2 | 2 | 2 | 2 | 1 |
| image-alt | 4 | 4 | 4 | 3 | 2 |
| input-image-alt | 1 | 1 | 1 | 1 | 1 |
| keyboard-operable | 3 | 3 | 1 | 2 | 0 |
| label-in-name | 2 | 2 | 2 | 2 | 0 |
| link-name | 3 | 3 | 3 | 3 | 3 |
| list-structure | 3 | 3 | 3 | 0 | 0 |
| meta-refresh | 1 | 1 | 1 | 0 | 1 |
| moving-content | 1 | 1 | 1 | 1 | 0 |
| nested-interactive | 2 | 2 | 2 | 0 | 0 |
| table-headers | 2 | 2 | 1 | 2 | 1 |
| target-size | 2 | 2 | 0 | 2 | 0 |
| use-of-color | 1 | 1 | 1 | 0 | 0 |
| valid-lang | 1 | 1 | 1 | 1 | 0 |
| viewport-zoom | 1 | 1 | 1 | 0 | 0 |
| widget-name | 3 | 3 | 3 | 3 | 1 |

## Independent check: GOV.UK accessibility-tool-audit

142 test pages, each demonstrating ONE failure (MIT licence, by the UK Government Digital Service; we did not write or tune them). A page is a candidate detection when the engines report a failure or best-practice issue beyond what an empty control page already reports (control: landmarks). Every candidate was then compared by hand with the test's description.

| | Pages |
|---|---|
| **Detected, and related to the planted failure** (three engines merged) | **55 of 142 (39%)** |
| Something was reported, but unrelated to the planted failure (not counted) | 18 |
| Nothing reported | 69 |
| Candidates by engine alone: axe-core / IBM / HTML_CodeSniffer (not hand-reviewed) | 43 / 56 / 43 |

The suite's own 2017 to 2019 results show that 50 of these 142 failures were not reported as a failure by ANY of the 13 tools it tested (for example plain language or consistent navigation: no automation can judge them). On the 92 failures that at least one of those tools reported, we confirm **54 (59%)**.

The hand review (`fixtures/benchmark/govuk-review.json`) was done by an AI assistant comparing each reported rule with the test's description. An accessibility specialist should re-check it before these numbers are quoted outside the team.

### Reported by another tool in 2017 to 2019 but not by us now

- buttons-uninformative-alt-attribute-value-on-image-button
- content-first-instance-of-abbreviation-not-expanded
- content-plain-language-is-not-used
- css-non-decorative-content-inserted-using-css
- html-empty-paragraph
- html-pre-element-without-code-element-inside-it
- html-spacer-image-found
- html-start-and-close-tags-dont-match
- images-a-distraction-is-present-an-animated-gif
- images-image-alt-attribute-contains-image-file-name
- images-image-has-alt-and-title-that-are-different
- keyboard-access-accesskey-attribute-used
- keyboard-access-concertina-items-dont-get-keyboard-focus
- keyboard-access-fake-button-is-not-keyboard-accessible
- keyboard-access-keyboard-focus-is-not-indicated-visually
- keyboard-access-lightbox-close-button-doesnt-receive-focus
- keyboard-access-link-with-a-rolebutton-does-not-work-with-space-bar
- language-of-content-text-language-changed-without-required-change-in-direction
- links-adjacent-links-going-to-the-same-destination
- links-link-contains-only-a-full-stop
- links-link-launches-new-window-with-no-warning
- links-link-not-clearly-identifiable-and-distinguishable-from-surrounding-text
- links-link-text-does-not-make-sense-out-of-context
- links-link-text-with-identical-title
- links-link-to-,-invalid-hypertext-reference
- links-link-to-an-image-no-text-alternative
- links-link-to-javascript-invalid-hypertext-reference
- links-links-with-the-same-text-go-to-different-pages
- links-non-specific-link-text
- multimedia-embedded-audio-file-is-missing-text-alternative
- multimedia-embedded-video-file-is-missing-text-alternative
- tables-table-is-missing-a-caption
- tables-table-that-only-has-th-elements-in-it
- typography-justified-text-found
- typography-very-small-text-found
