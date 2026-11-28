# ADR 0015: Outbound webhooks

- **Status:** Accepted
- **Date:** 2026-11-28

## Decisions
- **Events:** `scan.completed`, `scan.failed`, `report.ready`, `report.failed`, and `ping` (only when an administrator asks
  for a test). Each is a small JSON envelope `{id, type, created_at, data}`; `data` carries ids and a path into `/v1`, never
  page content.
- **One row per event per endpoint** (`webhook_deliveries`), unique on `(endpoint, event)`, so emitting twice or redelivering
  a task never sends twice. The event id is the same on every retry (`A11y-Event-Id`), so receivers can de-duplicate. What
  was sent is fixed once recorded; only delivery progress can change.
- **Signed.** `A11y-Signature: t=<unix>,v1=<HMAC-SHA256 of "<t>.<raw body>">` with a per-endpoint secret shown once at
  creation or rotation and stored encrypted. Receivers must reject old timestamps. A rotated secret replaces the old one at
  once. `webhooks.verify` is the reference implementation, used by our tests and shown in the reference page.
- **SSRF.** The address is customer-supplied, so it is checked with the same rules as the scanner when it is added AND on
  every delivery (a name that later points inside our network is blocked, simulated in a test). The request connects to the
  checked address, with the real host name for `Host` and TLS verification. Redirects are never followed. https is required
  (plain http only for local development hosts). The address of an endpoint cannot be edited: to move it, create a new one,
  so a secret is never silently handed to a different server.
- **Reliable without holding resources.** A delivery is claimed with one conditional `UPDATE` (so two workers cannot both send
  it), the HTTP call happens with no database connection held, then the result is written. Retries back off (1 minute, 5
  minutes, 30 minutes, 2 hours, 6 hours) and are driven by a once-a-minute sweeper that also frees claims whose worker
  vanished, so a restart loses nothing. The cross-tenant sweeper only reads; changes happen inside each organisation's own
  session.
- **Health.** `410 Gone` switches an endpoint off at once; an endpoint whose deliveries are abandoned many times in a row
  (setting `webhooks.limits.disable_after_failures`) is switched off and the organisation's administrators are emailed
  (`webhook.disabled`). Switching it back on clears the history. An administrator can retry an abandoned delivery by hand.
- **Controls.** Setting `webhooks.limits` (endpoints per organisation, attempts, timeout, https requirement; per plan or
  organisation); feature flag `webhooks`; plan entitlement `api_access`. Creating, changing, rotating, deleting and
  retrying are audit-logged. Response bodies are never stored.
- **UI:** `/org/webhooks` (endpoints, one-time secret, test, turn off/on, rotate, delete, delivery history with retry) and a
  Webhooks section in the API reference with the format and a verification sample.

## Not built yet
- Per-endpoint custom headers, payload filtering by organisation resource, and an event replay window longer than the history.
