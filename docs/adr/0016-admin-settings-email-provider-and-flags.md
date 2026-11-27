# ADR 0016: Email provider and feature flags as admin settings

- **Status:** Accepted
- **Date:** 2026-11-28

## Decisions
- **Email provider (`notify.provider`).** Mode `environment` (default) keeps using SMTP_* and MAIL_FROM; mode `smtp` uses an
  admin-set host, port, security (starttls, tls, none), username, password, from address and name, and reply-to. The password
  is a write-only secret (encrypted at rest, never returned, kept when the form is saved without it). The setting is read at
  send time, so changing the mail server needs no deploy. Guards refuse credentials over an unencrypted connection, unencrypted
  mail to anything but a local development inbox, invalid addresses, and line breaks (header injection). It is flagged high
  risk. The existing "Send a test to me" in the Emails tab is how an administrator checks a change.
- **Feature flags (`flags`).** One boolean per feature in a typed setting, so scopes (global, plan, organisation), versions,
  audit and rollback come from the settings framework. Flags: `public_api`, `webhooks`, `vpat`, `crawl_scans`,
  `notification_center`. A server check refuses cleanly (`feature_disabled`, 403, or 503 with `Retry-After` for the API), the
  organisation can read its own flags (`GET /org/flags`) so the UI leaves out what is off, and the list of enforcement points
  is kept beside the code (`FLAG_USES`). Plan entitlements (what a plan includes) and flags (an operational switch) are
  deliberately separate.

## Not built yet
- Per-percentage rollouts and scheduled flag changes; a managed email provider API (SES, Postmark) beyond SMTP.
