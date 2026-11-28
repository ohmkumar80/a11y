# ADR 0019: Entitlement overrides, coupon campaigns and AI code-fix credits

- **Status:** Accepted
- **Date:** 2026-11-28

## Decisions
- **Entitlement overrides.** A platform administrator can set an exception for ONE organisation and feature (a negotiated limit,
  a feature switched off, an early feature the plan lacks), with a required reason and an optional end date. It replaces the
  plan's value for that feature, so quotas, seats, API access and own-AI-accounts all honour it through one function
  (`billing.entitlement`). An expired override simply stops applying (no cron). The organisation can read its overrides (row-level
  security) but not change them (the application role has no write grant); cross-tenant administrator reads never pick up another
  organisation's override because the lookup is restricted to the session's own organisation. Setting and removing are
  audit-logged (platform log and the organisation's own log, so the customer can see them). The plan page shows "a custom limit has
  been set for your organisation". Switch-type entitlements (`api_access`, `byok_ai`) are never shown as usage meters.
- **Coupon campaigns.** `POST /admin/coupons/bulk` makes up to 500 random, unique codes (`PREFIX-XXXXXXXX`, an alphabet without
  0, O, 1, I) under a campaign name, single-use by default, in one audited action. A campaign list shows codes, redemptions and how
  many are still active, and one action switches off every code of a campaign (for a leak). The codes are shown once with copy and
  CSV download. One coupon per organisation is unchanged, so "stacking" is not an issue yet.
- **AI code-fix credits.** The plans already carry `ai_code_fixes_monthly`; the copilot now uses it. A credit is reserved
  atomically when a fix is requested (the same reservation machinery as scan credits, inside a savepoint so a refusal leaves
  nothing behind) and **charged only for a fix an AI model produced and our checks accepted**. Ready-made recipes, cache hits,
  validation failures, "needs review" outcomes and crashes cost nothing, and a stale reservation is settled by the sweeper by the
  same rule. When the month's credits run out the request is still accepted but only recipes may answer, the model is never called,
  and the person is told why. The dialog says before the click what costs a credit and afterwards when one was used.

## Not built yet
- Plan versions with grandfathering (a price or limit change that leaves existing customers on their old terms) and stacking rules.
  These need the Razorpay price-quote work first, so they come with it.
