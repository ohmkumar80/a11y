import type { Page } from "@playwright/test";
import settings from "./settings-fixture.json" with { type: "json" };

const org = (id: string, name: string, plan: string, status: string) => ({ id, name, plan_id: plan, status, trial_ends_at: status === "TRIALING" ? "2026-12-10T00:00:00Z" : null, active_users: 2, created_at: "2026-11-01T00:00:00Z" });

export const SUBSCRIPTION = {
  plan: { id: "TRIAL", name: "Trial" },
  status: "TRIALING",
  trial_ends_at: new Date(Date.now() + 5 * 86_400_000).toISOString(),
  seats: { used: 3, limit: 3 }, // full: exercises the warning state
  quotas: [
    { feature: "urls_monthly", enabled: true, used: 4, limit: 10 },
    { feature: "ai_code_fixes_monthly", enabled: true, used: 0, limit: null },
  ],
  coupon: null,
};

const PLANS = [
  { id: "TRIAL", name: "Trial", description: "", is_public: false, is_active: true, sort_order: 0, entitlements: [{ feature_key: "seats", enabled: true, limit_value: 3 }, { feature_key: "urls_monthly", enabled: true, limit_value: 10 }], prices: [] },
  { id: "GROWTH", name: "Growth", description: "", is_public: true, is_active: true, sort_order: 2, entitlements: [{ feature_key: "seats", enabled: true, limit_value: null }], prices: [{ currency: "INR", cycle: "MONTHLY", amount_minor: 499900 }] },
];

/** Mocks every /api/admin/* call the admin UI makes. */
export async function mockAdminApi(page: Page) {
  await page.route("**/api/admin/**", (r) => {
    const url = new URL(r.request().url());
    const p = url.pathname.replace(/^\/api/, "");
    if (r.request().method() !== "GET") return r.fulfill({ json: {} });
    if (p === "/admin/tenants") return r.fulfill({ json: [org("a1", "Acme Ltd", "TRIAL", "TRIALING"), org("b2", "Beta Co", "GROWTH", "ACTIVE")] });
    if (p === "/admin/trial-funnel") return r.fulfill({ json: { by_status: { TRIALING: 1, ACTIVE: 1 }, signups_last_30_days: 2, trials_ending_within_7_days: 1 } });
    if (p === "/admin/plans") return r.fulfill({ json: PLANS });
    if (p === "/admin/coupons") return r.fulfill({ json: [{ id: "c1", code: "WELCOME20", discount_type: "PERCENTAGE", discount_value: 20, valid_until: null, max_redemptions: 100, current_redemptions: 3, applicable_plan_ids: [], is_active: true }] });
    if (p === "/admin/settings") return r.fulfill({ json: settings });
    if (p.endsWith("/history")) return r.fulfill({ json: [{ version: 2, status: "published", comment: "Raise limit", created_at: "2026-11-20T00:00:00Z", published_at: "2026-11-20T00:00:00Z", restored_from: null }] });
    if (p.startsWith("/admin/settings/")) return r.fulfill({ json: { key: p.split("/").pop(), source: "global (v2)", version: 2, value: p.endsWith("ai.providers") ? { items: [{ id: "main", type: "openai", display_name: "OpenAI", base_url: null, region: null, api_key: { $secret: true, set: true, hint: "••••ab12" }, options: {}, data_policy: { zero_retention: true, processing_regions: ["us"], gov_approved: false }, is_enabled: true }] } : { length_days: 14, plan_id: "TRIAL", grace_days: 0, after_expiry: "LOCKED_READ_ONLY", reminder_days_before: [3, 1] } } });
    return r.fulfill({ status: 404, json: { detail: "not mocked" } });
  });
}
