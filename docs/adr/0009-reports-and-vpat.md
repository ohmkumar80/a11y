# ADR 0009: Reports and the VPAT

- **Status:** Accepted
- **Date:** 2026-11-27

## Decisions
- **One pipeline, gated.** A report is a row (`reports`) rendered by the `docs` worker. Every file passes a gate before it is
  stored: PDF → veraPDF PDF/UA-1 (ADR 0008); DOCX → `check_docx` (title, language, Heading styles in order, repeating table
  header rows, picture alt text); CSV → schema check. A file that fails is never stored or offered; the customer sees a plain
  message and the failure is logged. Finished reports are never re-rendered (a template change affects new reports only);
  regenerating is an explicit request.
- **Deterministic content.** Text comes from the stored scan, never from a model; a test checks the narrative's numbers
  against the tables. Page content (HTML snippets, selectors) is untrusted: Jinja autoescape + sandbox, and CSV cells cannot
  become spreadsheet formulas.
- **Templates are code for now** (sandboxed Jinja2, strict undefined, a data model each, version id recorded on every
  report). The registry is the interface for admin-editable, versioned templates with preview and two-person approval, which
  are not built yet. Email templates are separate work.
- **VPAT never overstates.** Automation may *suggest* "Does Not Support" (failures on every scanned page) or "Partially
  Supports", and **never proposes "Supports"**. A criterion with no automated issue, or with no automated check, stays "Not
  Evaluated". A person edits levels and remarks (remarks required for partial/does-not-support and for overriding a
  failure), then signs off (name, role, fixed statement; audit-logged). **Export is refused until signed off**, the document
  states when criteria are still unevaluated and when the standard mapping lacks expert sign-off, and it says it covers WCAG
  web criteria only (not the software/hardware/documentation chapters of the full VPAT editions).
- **Roles.** Company admins edit, sign off, reopen and export a VPAT; every member can generate audit reports and read VPATs.
- **Storage.** File bytes live in Postgres (`bytea`, 25 MB cap, tenant RLS) until the cloud target (ADR 0002) is chosen; the
  column moves to object storage without changing the API.
- **Package boundary.** VPAT *logic* (levels, defaults, validation, drafting) is in `a11y_core` so the API image (no
  WeasyPrint, no JRE) can use it; rendering is in `workers/documents`.

## Not done
Admin-editable templates and the template editor; email templates and the notification catalogue; the 508/EU/INT chapters
of the VPAT editions beyond the WCAG tables; per-page and per-element screenshots in reports; localisation of templates
(Indian-language report text); scheduled/regression reports; report retention and deletion on request.
