# ADR 0006: Admin-configurable settings, secrets, and AI configuration

- **Status:** Accepted (implements PROJECT_PLAN 3.11.1 / 3.11.2)
- **Date:** 2026-11-27

## Decisions
- **One typed registry** (`a11y_core.config.definitions`) declares every admin-configurable setting: key, Pydantic
  model, default, allowed scopes (`global → plan → org`), guardrail. `GET /admin/settings` returns the JSON Schema per
  setting so the admin UI generates its forms from it.
- **Storage is append-only** (`setting_versions`). The effective value is the latest *published* row per
  `(key, scope, scope_id)`; rollback publishes a copy of an older version as a new one. Every write requires a comment and
  writes an `audit_log` row listing changed JSON *paths* (never values).
- **Privilege split enforces the principle:** `a11y_app` can only `SELECT` settings (RLS lets it see global/plan rows and
  only its own org's overrides); writes use the audited `a11y_admin` role, serialised per setting by an advisory lock.
  The same pattern covers plans, entitlements, coupons (the app may only bump `current_redemptions`) and subscriptions
  (a tenant cannot change its own plan).
- **Secrets** are Fernet-encrypted (key ring: first key encrypts, all decrypt → rotation). They are write-only: the API
  returns `{set, hint: "••••abcd"}`, clients cannot submit ciphertext, and a re-save without plaintext keeps the stored
  secret (matched by list item `id`). `ENV=production` refuses the public dev key. **Open:** move the key ring to a
  KMS/Key Vault-backed source once the cloud target (ADR 0002) is final; the `SecretBox` interface stays the same.
- **Cache:** Redis holds the current row per scope, deleted on write plus a 30 s TTL; Redis down ⇒ direct DB reads. No
  pub/sub yet because there is no in-process cache layer to invalidate. A reader racing a writer can serve the old value for
  at most the TTL.
- **AI configuration is settings, not tables:** `ai.providers`, `ai.models`, and one `ai.route.<task>` per task (so
  per-plan/per-org overrides work per task). This deviates from the separate `AIProvider/AIModel/AITaskRoute` tables in
  3.11.2 on purpose: settings give versioning, audit, rollback and live reload for free. Usage metering stays relational
  (`ai_usage`, one row per provider *attempt*, append-only, RLS).
- **`LLMGateway`** is the only code path to a model: resolves route → providers/models, skips anything disabled,
  misconfigured or lacking the task's capability, tries primary then fallbacks with a timeout, meters every attempt,
  enforces a per-org monthly budget, and raises `AIUnavailable` so callers degrade to deterministic output.

## Known gaps (tracked, not hidden)
- Only the `fake` adapter exists. Real adapters (OpenAI, Anthropic, Bedrock, …) and the LiteLLM-vs-native decision are next;
  the Phase 1 exit criterion needs at least two live ones.
- Cross-setting integrity (a route naming a model that does not exist, disabling the last model for a task) is handled at
  call time by skipping, not rejected at publish time yet.
- Draft → "test connection" → evaluation-gated publish, staged rollout and two-person approval (`high_risk` is declared
  but not enforced) are Phase 2 per the plan.
- Feature flags need merge-by-name semantics across scopes, which the whole-value override model does not give; they will
  be their own table.
- Super Admin sign-in is access-token-only (no refresh, no MFA). MFA is required before any production use.
