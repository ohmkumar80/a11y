# ADR 0014: The public API (/v1), API keys and the reference page

- **Status:** Accepted
- **Date:** 2026-11-28

## Decisions
- **Keys.** Format `a11y_<organisation id>_<43 random characters>`. The organisation is in the key (not secret), so the key
  is looked up under normal tenant row-level security; only a SHA-256 of the whole key is stored, so a database leak
  yields no working keys. The `a11y_` prefix lets secret scanners recognise a leaked key. A key is shown once at creation.
  A key's identity, hash and scopes cannot be changed (the table grants UPDATE only on `last_used_at` and `revoked_at`):
  to change what a key can do, issue a new one.
- **Scopes:** `scans:read`, `scans:write`, `reports:read`, `reports:write`, `audit:read`. Each endpoint states its scope in
  the published description.
- **Checked on every request:** shape, hash, not revoked, not expired, the creator is still an active member, the plan still
  includes `api_access`, the scope, and a per-key rate limit (setting `api.limits`, per plan or organisation, with a cap on
  keys per organisation and an optional maximum key lifetime). Every authentication failure gets the same answer, so a
  caller cannot tell which part of a guess was right. An API key acts as a *member*, never an administrator, and cannot use
  the session API.
- **One implementation.** `/v1` endpoints are typed and documented wrappers over the same handlers the web app uses, so a
  scan started by key is billed, rate-limited, SSRF-checked, tenant-isolated and quota-reserved identically.
- **Idempotency.** `Idempotency-Key` on `POST /v1/scans` and `POST /v1/scans/{id}/reports`: the first request does the work
  and its answer is kept 24 hours; a repeat gets the same answer (`Idempotent-Replay: true`). A request that failed releases
  its key, so a corrected retry is allowed. A concurrent duplicate gets `409 idempotency_in_progress`.
- **Errors** have one shape, `{detail, code, field}`; `detail` is for people, `code` is stable for programs.
- **Published description** at `/v1/openapi.json` (public; using the API is not): generated from the code, with a scope on
  every operation, the three auth/limit errors documented on each, and a security scheme. The accessible reference page
  (`/developers`) is rendered by our own components from that document instead of a third-party renderer, so the page
  itself meets WCAG 2.2 AA. A test fails when the saved copy used by the web tests drifts from the real description.
- **Plans.** `api_access` is a plan entitlement (data, editable in `/admin`). Launch placeholders: on for Trial (so a design
  partner can try it), off for Starter, on for Growth and Enterprise.
- **Audit.** Creating and revoking keys is audit-logged and readable through `GET /v1/audit-log` (scope `audit:read`).

## Not built yet
- Outbound webhooks (so integrations need not poll), per-key IP allow-lists, key rotation helpers, and an SDK.
- The code-fix and screenshot endpoints are web-app features and are not in v1 yet.
