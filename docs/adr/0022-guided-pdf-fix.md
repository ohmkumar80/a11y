# ADR 0022: Guided PDF fix

- **Status:** Accepted
- **Date:** 2026-11-28

## Decisions
- **Scope: what can be fixed without guessing.** A person can set the document title and language, write the text alternative of
  each tagged figure, and change the level of each tagged heading. Nothing is added to or removed from the page content, so
  what a sighted reader sees does not change. The things that need real remediation (tagging an untagged file, reading order,
  table headers, decorative images, forms, contrast) are not in this slice. An untagged file says plainly that only its title
  and language can be set here.
- **A plan, not code.** The edits are plain data (`FixPlan`), validated twice: by the API against the structure stored with the
  audit, and again by the worker against the real file. A plan that refers to something no longer in the file is refused, never
  guessed at. Elements are addressed by their PDF object number, which is stable inside one file; the rare direct (non-indirect)
  elements are listed as not editable.
- **The original is never touched.** The build reads the original (only if it is `CLEAN`, through the checksum-verifying
  reader), applies the plan to a copy with pikepdf, re-checks the copy with the same audit engine, and stores the result as a
  **new document** linked to the original (`derived_from`). Because the copy is an ordinary document, download, retention,
  deletion, results and the public API all work for it with no special cases. It is stored encrypted like any file.
- **The gate.** A copy is produced only if it opens, has the same number of pages, and its re-check shows no NEW critical or
  serious problem. Otherwise nothing is stored, the person is told that, and the pages are given back. A copy that still has
  problems is delivered, labelled with what was fixed and what remains: "better, and honest about it", not a claim of
  conformance. The result always repeats that a person must still judge alternative text and reading order.
- **We never add the "I follow PDF/UA" label.** Rule 5-1 (the PDF/UA identification in the metadata) is a claim of conformance.
  We leave it as a minor remaining item, explained in plain words, to be added by a person once the file has really been checked.
- **XMP metadata only when needed.** Writing metadata makes the checker evaluate a title the file never had, which can look like a
  new problem. The engine writes XMP when a title is being set, or updates it when it already exists; a language-only plan on a
  file with no XMP sets only the catalog language.
- **Quota.** One reservation of the document's pages (`document_pages_monthly`) covers the build and its re-check, settled once:
  charged when a copy was produced, given back when the build failed or was refused by the gate. One fix in progress per document
  (a unique index), so a plan cannot be changed while it builds. Sweepers re-queue builds that were never picked up and settle
  reservations a crash left behind.
- **Heading text is read best-effort** from the page content through the font's ToUnicode map (so the person can tell headings
  apart); anything it cannot read is shown as "text not available". Bounded in nodes, depth and operations because the file is
  untrusted.
- **Derived data goes with the file.** Deleting an original deletes its plans; the fixed copy is its own document and stays.

## Not built yet (honest list)
- Page previews and marked problem areas; the person finds an image by its page number.
- Reading-order and table-header editors; decorative images; automatic tagging of untagged files.
- A human reviewer who does the fix on a customer's behalf (the reviewer role, queue and consent) is the next slice and reuses this
  engine and plan.
- `/v1` endpoints for fixes, a webhook event, AI-suggested alternative text (needs the data-policy slice first).
