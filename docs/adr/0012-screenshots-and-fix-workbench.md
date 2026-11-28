# ADR 0012: Screenshots and the Fix Workbench

- **Status:** Accepted
- **Date:** 2026-11-27

## Decisions
- **One picture per page, not one per finding.** The scanner saves a JPEG of the top of each page (1280 px wide,
  at most `screenshot_max_height` tall, quality configurable) and every finding already stores its element's rectangle
  in page pixels. The Workbench crops and outlines in the browser. This keeps storage small (a typical page is
  100 to 300 KB, a scan of 25 pages a few MB) and means a finding never needs a second image job.
- **Admin-configurable and bounded** (setting `scan.engines`, per plan or organisation): `screenshots` on/off,
  `screenshot_pages` (most pages per scan that keep one), `screenshot_max_height`, `screenshot_quality`. A picture over
  1.5 MB is dropped (the table refuses 2 MB); a failed capture never fails the scan.
- **Truthful about what was saved.** Pages taller than the cap are marked `truncated`; an element below the cap or one
  that is hidden or zero-sized is reported in words, never drawn at a wrong place.
- **Positions are page coordinates, including inside iframes.** The runner adds each enclosing frame's offset (a defect
  found while building this: framed elements were previously frame-relative) and the top page's scroll.
- **Private and immutable.** Table `page_screenshots` is tenant-scoped with forced row-level security; a saved
  screenshot cannot be updated by the application role. It is served only through an authenticated endpoint
  (`Cache-Control: private`, `nosniff`); the browser fetches it with the token and shows a local copy.
- **Stored in Postgres for now**, like reports (ADR 0009); object storage replaces it when the cloud target is
  chosen (ADR 0002). Screenshots contain whatever the customer's page showed. They are deleted with the scan, and the
  retention policy (how long scans are kept) is still to be decided.
- **Accessible by construction.** The outline is a white ring inside a dark-red ring (visible on light and dark
  backgrounds, not colour alone). The picture has a text alternative and the same facts appear as text (element HTML
  and selector, criteria, message). A scrollable whole-page view is keyboard focusable. Selecting a problem moves focus
  to its heading, with Previous, Next and Back-to-list controls, so the page works at any width and by keyboard.
- **The Workbench is a master-detail page** (`/workspace/scan/workbench?id=`): problem list, where it is, guidance
  (ADR 0011's library) and the checked code fix, reusing the same components as the finding dialog.

## Consequences
- Fixed headers or lazy-loaded content can make the saved picture differ slightly from what a visitor sees.
- A "mark as fixed / ignore" workflow and a re-scan of a single page are natural next steps and are not built.
