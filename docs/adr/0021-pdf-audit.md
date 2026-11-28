# ADR 0021: PDF accessibility audit

- **Status:** Accepted
- **Date:** 2026-11-28

## Decisions
- **What is checked.** The PDF/UA-1 (ISO 14289-1) machine checks from veraPDF, plus three direct checks veraPDF does not
  make: pages that are only pictures (scans), a long document with no bookmarks, and the facts shown on the results page
  (tagged, language, title). Findings are grouped per rule with a count and the pages veraPDF reports. AI layout analysis is
  not part of this first cut: it needs the provider and data-policy decisions in the Phase 3 plan.
- **Plain language comes from a reviewed catalog, not from the model.** `rules/documents/pdfua1.yaml` holds severity, why it
  matters, how to fix it, WCAG criteria and "needs a person" for each rule we have seen veraPDF report, keyed exactly as
  veraPDF keys it (`7.3-1`). Rules not in the catalog fall back to their clause, or to a generic entry, and are marked as not
  yet explained and as needing a person. A failure is never hidden because we lack wording. Entries are `draft` until an
  accessibility specialist reviews them, the same policy as the web rule content.
- **Honest results.** The summary always carries a caveat: automated checks cannot judge whether alternative text is
  meaningful, whether the reading order is logical or whether colours have enough contrast. "No problems found" never reads as
  "accessible". Severities use the same four words as the web scanner.
- **Quota counts pages, not files.** `document_pages_monthly` (placeholder limits per plan; the owner edits them in /admin).
  Pages are reserved when the audit is requested, so a limit cannot be raced past, and settled once: charged when the audit ran
  (including when it found problems, or the customer's file turned out to be damaged), given back when the failure was ours or
  the customer deleted the file first. Sweepers re-queue audits that were never picked up and settle reservations a crash left
  behind. One audit per document at a time.
- **Only a CLEAN file is read**, through the same function as downloads, which verifies the stored checksum.
- **Results are derived data and go with the file.** Deleting a document deletes its audits and findings. The usage record stays.
- **Public API.** `/v1/documents` with scopes `documents:read` and `documents:write`, idempotent uploads and audits, the same
  error shape. Internally it calls the same functions as the web app, so limits and isolation cannot differ.
- **The results page lists findings; it does not preview pages.** A document workbench with page images and marked problem
  areas, an editable alt-text and reading-order editor, and remediation are later slices.

## Known limits
- Rule wording exists for the rules observed so far (11) plus clause fallbacks. More arrive as real files exercise veraPDF.
- veraPDF's JSON lists only the first failures of a rule, so `count` is exact but the page list can be partial (the finding says
  how many pages in total when it knows).
- A scanned page is recognised as "an image and no text operators and no form XObject"; a page whose text sits only inside an
  XObject is not reported as a scan.
- Direct checks look at up to the first 200 pages.
- There is no audit report file (PDF/DOCX) yet, and no webhook event for a finished audit.
