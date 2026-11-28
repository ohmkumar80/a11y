# ADR 0023: Human review of documents

- **Status:** Accepted
- **Date:** 2026-11-28

## Decisions
- **Reviewers are platform staff.** A new role, `REVIEWER`, sits beside `SUPER_ADMIN` as a platform role: no organisation (the
  database constraint now says exactly that), sessions in `platform_sessions`, the same rotating cookie, and the **same two-step
  verification policy** as administrators (one shared setting). A reviewer cannot reach any customer or admin endpoint. The owner
  creates reviewers in `/admin` (or with `python -m a11y_api.admin_cli --create-reviewer EMAIL`), can set a new password and can
  switch one off. Switching off is checked against the database on every request, so it takes effect at once rather than when an
  access token expires. The platform owner can also use the console.
- **A request is the customer's consent.** "Ask a person to check this" shows the consent text in full, requires an explicit tick,
  records the consent version, and is the only thing that lets a reviewer see a file. The text says who will open it, that every
  access is logged, and that the original is never changed.
- **A reviewer sees as little as possible, as late as possible.**
  - *Before claiming:* the queue shows only counts and times (pages, findings by severity, number of figures and headings, whether
    it is tagged, due time). No file name, no customer note, no organisation, no content.
  - *Enforced in the database:* a reviewer's session can read only requests nobody has claimed and the ones they hold, and change
    only those (row-level security on `document_reviews`). A direct query from that session finds no rows in documents, audits,
    fixes, users, organisations or the audit log; this is tested.
  - *After claiming:* the API checks the claim, then opens an ordinary tenant session for that one organisation. Every claim,
    original download, result download, fixed-copy build and release writes a row in the **customer's own audit log**.
  - A reviewer holds at most five files; a file held past an admin-set timeout returns to the queue; the owner can take one back.
- **Same tools, same engine.** The reviewer works in the same fix editor the customer has (one shared component) and the same
  build, gate and re-check (ADR 0022). The customer cannot change the plan while a reviewer holds the file. The reviewer's build
  does not use the customer's document pages: the review covers it.
- **Two ways to finish.** *Deliver*: only possible if a fixed copy was built during this review; the customer gets the copy as a
  normal document, with a message. *Decline*: a reason is required ("we could not improve this file"); the credit is given back.
  Either way the customer gets an email (new `document.review_done` event, editable in `/admin` → Emails) and a `review.completed`
  webhook. The customer is never told who the reviewer was.
- **Credits.** `document_reviews_monthly` (placeholder limits: trial 0, starter 2, growth 20, enterprise unlimited). One credit is
  reserved when the request is made, charged when a review is delivered, given back when it is declined or cancelled. A customer
  can cancel until a reviewer takes the file. Sweepers settle credits a crash left behind.
- **Everything tunable is a setting:** `documents.review` (on or off, target hours, claim timeout, open reviews per organisation,
  the cost of an hour of reviewer time) at global, plan or organisation scope, and the `human_review` feature flag.
- **Unit cost is measured, not guessed.** Each review records the time from claiming to finishing and the minutes the reviewer
  reports. `/admin` → Reviews shows turnaround against the target, the share finished on time, the average time, and, once the
  hourly cost is set, the cost of a review and of a page. This is the figure the plan quotas must cover.

## Not built yet (honest list)
- A reviewer's own two-step enrolment prompt is the generic one; there is no reviewer-specific onboarding or password-change screen
  (the owner sets a new password).
- No paging or alerting when a review becomes overdue (the admin page shows it; `/admin/ops` does not yet).
- No reviewer skills, assignment rules or fair-share between reviewers: it is a shared queue, oldest deadline first.
- No `/v1` endpoints for reviews; reviews are web-only for now.
- Page previews and reading-order editors are still missing for reviewers and customers alike (ADR 0022).
- Reviewers see the file's content, so the data-policy slice (regions, zero-retention for any AI use) still has to come before any
  AI is allowed near it; nothing here sends a customer file to an AI provider.
