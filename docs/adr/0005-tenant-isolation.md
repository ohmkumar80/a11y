# ADR 0005: Tenant isolation with Postgres Row-Level Security

- **Status:** Accepted
- **Date:** 2026-11-26

## Decision
- Three DB roles: `a11y_owner` (migrations; `FORCE ROW LEVEL SECURITY` so it is subject to policies), `a11y_app` (API and
  workers; not owner; `NOBYPASSRLS`), `a11y_admin` (`BYPASSRLS`, Super Admin only).
- Every request/job runs in one transaction that starts with `set_config('app.org_id', …, true)` (== `SET LOCAL`), safe with PgBouncer
  transaction pooling. Unset => no rows (fail closed).
- Pre-login lookups (login, reset) use a second setting, `app.auth_email`, which exposes exactly one `users` row.
- One-time tokens are `"<org uuid hex>.<secret>"`: the prefix opens the right tenant session; only a SHA-256 of the whole
  token is stored.
- `admin_session()` writes an `audit_log` row in the same transaction before any cross-tenant read; `audit_log` is append-only for the app role.
- `tests/test_rls_isolation.py` fails the build if any table with `organization_id` lacks forced RLS and a policy.

## Consequences
New tenant tables need: `organization_id`, `ENABLE` + `FORCE ROW LEVEL SECURITY`, a `tenant_isolation` policy, and a row in the isolation tests.
