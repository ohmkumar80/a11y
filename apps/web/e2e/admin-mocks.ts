import type { Page } from "@playwright/test";
import byokSchema from "./byok-schema-fixture.json" with { type: "json" };
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

export const EMAIL_EVENTS = [
  { key: "scan.completed", label: "Scan finished", audience: "actor", category: "scan", required: false, variables: { url: "The address that was scanned", summary: "A short summary", scan_id: "The scan's id" }, has_link: true,
    default: { subject: "Your accessibility scan of {url} is ready", intro: "The scan of {url} has finished. {summary}", action_label: "View the results", outro: "Automated tests find only some accessibility problems." }, enabled: true, edited: false },
  { key: "auth.reset_password", label: "Reset password", audience: "user", category: "account", required: true, variables: { token: "The one-time token" }, has_link: true,
    default: { subject: "Reset your password", intro: "We received a request to reset your password.", action_label: "Choose a new password", outro: "This link works for 1 hour." }, enabled: true, edited: false },
];

const PLANS = [
  { id: "TRIAL", name: "Trial", description: "", is_public: false, is_active: true, sort_order: 0, entitlements: [{ feature_key: "seats", enabled: true, limit_value: 3 }, { feature_key: "urls_monthly", enabled: true, limit_value: 10 }], prices: [] },
  { id: "GROWTH", name: "Growth", description: "", is_public: true, is_active: true, sort_order: 2, entitlements: [{ feature_key: "seats", enabled: true, limit_value: null }], prices: [{ currency: "INR", cycle: "MONTHLY", amount_minor: 499900 }] },
];

/** Tests can flip the platform-admin MFA policy the mocked API reports. */
export const mfaState = { superAdmin: "required" as "required" | "optional" | "off" };

/** Mocks every /api/admin/* call the admin UI makes. */
export async function mockAdminApi(page: Page) {
  await page.route("**/api/admin/**", (r) => {
    const url = new URL(r.request().url());
    const p = url.pathname.replace(/^\/api/, "");
    if (p === "/admin/security/mfa") return r.fulfill({ json: { super_admin: mfaState.superAdmin, org_admin: "optional", issuer: "a11y", environment: "development" } });
    if (p === "/admin/settings/auth.mfa") return r.fulfill({ json: { key: "auth.mfa", source: "default", version: null, value: { super_admin: mfaState.superAdmin, org_admin: "optional", issuer: "a11y" } } });
    if (p.startsWith("/admin/ai/providers/") && p.endsWith("/test")) return r.fulfill({ json: { ok: true, detail: "Connected.", model_id: "m", latency_ms: 120 } });
    if (p === "/admin/notifications/preview") {
      const b = r.request().postDataJSON() as { subject: string; action_label: string };
      if (b.subject.includes("{nope}")) return r.fulfill({ status: 422, json: { detail: "Scan finished, subject: {nope} is not available here. You can use: {url}, {summary}, {scan_id}.", field: "wording" } });
      return r.fulfill({ json: { subject: b.subject || "Your accessibility scan of https://example.com/ is ready", text: "Plain text body", html: `<!doctype html><html lang="en"><head><title>t</title></head><body><h1>${b.action_label || "View the results"}</h1></body></html>`, accessibility_problems: [] } });
    }
    if (p === "/admin/notifications/test") return r.fulfill({ json: { sent_to: "ops@example.com" } });
    if (r.request().method() !== "GET") return r.fulfill({ json: {} });
    if (p === "/admin/notifications/events") return r.fulfill({ json: EMAIL_EVENTS });
    if (p === "/admin/notifications/log") return r.fulfill({ json: [{ id: "n1", event: "scan.completed", label: "Scan finished", to: "ada@example.com", state: "SENT", attempts: 1, error: null, organisation: "Acme Ltd", created_at: "2026-11-27T01:00:00Z", sent_at: "2026-11-27T01:00:05Z" }, { id: "n2", event: "quota.reached", label: "Monthly scan limit reached", to: "bo@example.com", state: "FAILED", attempts: 4, error: "ConnectionError: smtp down", organisation: "Beta Co", created_at: "2026-11-27T02:00:00Z", sent_at: null }] });
    if (p === "/admin/settings/notify.templates") return r.fulfill({ json: { key: "notify.templates", source: "default", version: null, value: { items: [] } } });
    if (p === "/admin/ai/providers") return r.fulfill({ json: [{ id: "deepseek", type: "deepseek", display_name: "DeepSeek", base_url: null, is_enabled: true, key_set: true, data_policy: { zero_retention: false, processing_regions: ["cn"] }, models: [{ id: "deepseek-chat", model_name: "deepseek-chat", capabilities: ["text", "json"], is_enabled: true }] }] });
    if (p === "/admin/ai/presets") return r.fulfill({ json: { presets: { deepseek: { label: "DeepSeek", needs_endpoint: false, default_model: "deepseek-chat" }, azure_openai: { label: "Azure OpenAI", needs_endpoint: true, default_model: "" } }, tasks: { code_fix: ["text"], alt_text: ["vision"] } } });
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

export const BYOK = {
  eligible: true, upgrade_url: "/org#plan", provider_types: ["openai", "azure_openai", "deepseek"], schema: byokSchema, version: 1,
  usage_this_month: { calls: 3, tokens: 1200 },
  value: { enabled: true, providers: [{ id: "mine", type: "deepseek", display_name: "Our DeepSeek", base_url: null, region: null, api_key: { $secret: true, set: true, hint: "••••WXYZ" }, options: {}, data_policy: { zero_retention: false, processing_regions: [], gov_approved: false }, is_enabled: true }], models: [{ id: "mine-chat", provider_id: "mine", model_name: "deepseek-chat", capabilities: ["text"], context_window: 8192, input_cost_per_1m: 0, output_cost_per_1m: 0, is_enabled: true }], model_order: ["mine-chat"], only_tasks: [], fallback_to_platform: false },
};
