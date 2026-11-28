# ADR 0008: Accessible PDF generation (spike result)

- **Status:** Accepted
- **Date:** 2026-11-27
- **Question (plan 3.14 / Phase 0 spike):** does Chromium's tagged PDF reach PDF/UA-1 without repairs?

## Result
**No.** We use **WeasyPrint with `pdf_variant="pdf/ua-1"`** and gate every file with **veraPDF**.

| Same sample report (headings, lists, table with `<th>`, SVG chart, links), validated with veraPDF 1.31 `--flavour ua1` | Result |
|---|---|
| Chromium `page.pdf(tagged=True, outline=True)` | **FAIL**, 4 rules: 7.18.1 and 7.18.5 (link annotations not in the structure tree, no `/Contents`), 7.3 (Figure without alt), 7.1 (no XMP metadata) |
| WeasyPrint 70, `pdf/ua-1` | **PASS**, 106 of 106 rules |
| WeasyPrint 70, no variant (negative control) | FAIL: the validator is not vacuous |

Chromium's failures are repairable with a `pikepdf` post-processing step, but that means owning a PDF repair layer for
no benefit. WeasyPrint (BSD-3) produces a correct tag tree directly: language, title, `DisplayDocTitle`, XMP, H1 to H6,
lists, `Table/THead/TH/TD`, `Caption`, `Link`, and an SVG's `<title>` becomes the Figure's alt text.

## Stress test (400-row table over 9 to 21 pages, Tamil and Hindi paragraphs, images, code, running footer)
- Renders in about 1.4 s at about 200 MB. The table header row repeats on every page.
- In the container (`infra/docs-worker.Dockerfile`: Pango, `fonts-noto-core`, JRE, veraPDF) it passes, and the embedded
  fonts include Noto Sans Tamil and Noto Sans Devanagari. **Without Noto fonts installed Indian scripts would render as
  boxes**, so the font packages are part of the image, not optional.
- **One failure found and turned into a rule:** a decorative `<img alt="">` becomes a Figure with no alt and FAILS PDF/UA
  (also with `role="presentation"` or `aria-hidden`). A CSS background image is treated as an artifact and PASSES. Report
  templates must draw decoration with CSS backgrounds. `check_template_html` enforces this (and lang, title, headings,
  `<th>`, SVG `role="img"` + `<title>`) when a template is saved.

## Consequences
- `workers/documents` (`render_pdf_ua`, `validate_pdf_ua`, `check_template_html`) is the base for audit reports, VPAT PDFs
  and invoices. A PDF that fails veraPDF is never offered for download.
- **Passing veraPDF is necessary, not sufficient.** It checks machine-verifiable rules, not whether reading order, alt text
  or headings make sense. Those are covered by template tests and by the manual release checklist (NVDA/VoiceOver and a PDF
  reader). Matterhorn checkpoints that need human judgement remain human.
- veraPDF runs from `$VERAPDF_BIN`, `/opt/verapdf`, `verapdf` on PATH, or the `ghcr.io/verapdf/cli` image (CI, dev). Pin the
  image by digest before production.
- DOCX and CSV outputs are separate work with their own checks (plan 2.5).
