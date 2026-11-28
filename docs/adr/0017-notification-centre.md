# ADR 0017: In-app notification centre and email preferences

- **Status:** Accepted
- **Date:** 2026-11-28

## Decisions
- **One source.** Every email event (`a11y_core.notify.emit`) also writes an in-app item for each recipient who is a member, using
  the same wording the administrators edit (subject as title, introduction as text, the event's link). There is no second set of
  strings to keep in step. Items are unique per person and event instance, immutable (the application role may only set
  `read_at`), and private to the person: queries filter to the signed-in member, row-level security isolates organisations.
- **Preferences.** Only optional email is a choice: a member can turn off email for scan finished and scan failed
  (`user_preferences.email_scan`). Those emails are then logged as skipped with the reason, and the in-app item is still created.
  Account, security and billing email cannot be turned off.
- **Quiet UI.** The header shows `Notifications` and, when there are unread items, a count with the word "unread" (not colour
  alone). It refreshes on each page and once a minute while the tab is visible, with no live region, so nothing is announced
  unless the person goes to look. The list marks unread items with the word "Unread", offers Mark as read, Mark all as read,
  paging, and following an item marks it read. The link stays immediately before Help (SC 3.2.6).
- **Switch.** Feature flag `notification_center` (per plan or organisation) removes the link, the API (`feature_disabled`) and
  item creation; email is unaffected.
- **Transaction discipline.** `emit` looks up flags and wording before opening its transaction, so it never holds one database
  connection while waiting for another.

## Not built yet
- Per-event email preferences beyond "scan emails", digest emails, push notifications and mark-as-unread.
