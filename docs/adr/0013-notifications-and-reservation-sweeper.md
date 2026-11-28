# ADR 0013: Email events, editable wording, and the reservation sweeper

- **Status:** Accepted
- **Date:** 2026-11-27

## Decisions
- **One catalog of events** (`a11y_core.notify.EVENTS`): four account emails (confirm address, reset password, team
  invitation, sign-up with an existing address), trial ending, trial ended, scan finished, scan did not finish, and monthly
  scan limit reached. Each event declares who receives it, the variables it can fill, the default wording and where its
  link goes. Payment emails are added with the Razorpay work.
- **Layout is code, wording is data.** The HTML skeleton is fixed (language, title, one heading, real text, 17:1 body and
  8.6:1 link contrast, a visible address next to the link, a plain-text part). Admins change only the words through the
  setting `notify.templates`, so every change is versioned, audited and can be rolled back. A guard refuses
  placeholders the event cannot fill, generic link text ("click here"), and switching off a required email. Placeholders are
  filled by a plain `{name}` substitution, never `str.format`, so edited text cannot reach attributes or code, and every
  value is HTML-escaped. `check_email_html` proves the result is accessible and runs on every email in the tests and in the
  admin preview.
- **Delivery is logged and idempotent.** Table `notification_log` has one row per recipient and event instance; the unique
  key `(organisation, dedupe_key, recipient)` means a retried job, a redelivered task or a repeated schedule sends nothing
  twice. Sending is a separate task (`notify.deliver`, system queue) that retries with backoff up to 4 times, then marks the
  row `FAILED`. Only delivery progress can change on a row; who, what and the key cannot. Wording is applied at send time,
  and an email switched off after it was queued is skipped and logged as such.
- **Triggers.** Scan finished and scan failed go to the person who started the scan (organisation admins if that person is
  gone); failed-scan emails say whether the credit came back, and are not sent when the person is told in the response
  (queue down). Trial reminders use the existing `billing.trial.reminder_days_before`; only the tightest threshold already
  crossed is sent, once. Trial ended goes out when the trial locks. The monthly-limit email goes to organisation
  administrators once per month however many scans are refused.
- **Admin editor.** `/admin` Emails tab: the events table, an editor with the built-in text shown, the variables available,
  a live preview of the draft (with the accessibility check), a test send to the administrator's own address, and the recent
  delivery log across organisations (audited).
- **Orphaned-reservation sweeper** (every 10 minutes): a credit still `RESERVED` an hour after its scan ended, or whose scan
  no longer exists, is settled by the same rules as a live scan: kept for a finished scan or a customer fault, returned for
  a platform fault, a cancellation or a missing scan. Scans still queued or running are left to the stuck-scan sweeper.
  Settling is idempotent, so running it often is safe.

## Not built yet
- Per-user opt-out of optional emails and an in-app notification centre (1b).
- An admin setting for the email provider; SMTP is still configured by environment.
- Bounce and complaint handling; delivery here means "handed to the mail server".
