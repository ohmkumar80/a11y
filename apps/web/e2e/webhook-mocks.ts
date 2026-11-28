import type { Page } from "@playwright/test";

export const EVENTS = {
  "scan.completed": "A scan finished successfully", "scan.failed": "A scan did not finish",
  "report.ready": "A report is ready to download", "report.failed": "A report could not be produced",
};
const ep = (id: string, url: string, enabled: boolean, events: string[], over: object = {}) => ({
  id, url, description: "", events, enabled, disabled_reason: enabled ? null : "20 deliveries in a row failed.", secret_hint: "x9Qa",
  consecutive_failures: enabled ? 0 : 20, last_success_at: null, created_at: "2026-11-20T00:00:00Z",
  last_delivery: enabled ? { status: "SENT", at: "2026-11-27T01:00:00Z", response_status: 200, error: null } : { status: "ABANDONED", at: "2026-11-27T01:00:00Z", response_status: 500, error: "HTTP 500" }, ...over,
});
const delivery = (id: string, status: string, error: string | null = null) => ({
  id, event_id: `e-${id}`, event_type: "scan.completed", status, attempts: status === "ABANDONED" ? 6 : 1, response_status: error ? 500 : 200, error,
  created_at: "2026-11-27T01:00:00Z", delivered_at: status === "SENT" ? "2026-11-27T01:00:02Z" : null, next_attempt_at: null,
});

/** Stateful fake of /org/webhooks. */
export async function mockWebhooks(page: Page, opts: { entitled?: boolean; switchedOff?: boolean } = {}) {
  const eps = [ep("w1", "https://hooks.example.com/a11y", true, ["scan.completed"]), ep("w2", "https://old.example.com/hook", false, ["scan.failed"])];
  const calls: string[] = [];
  await page.route("**/api/org/webhooks", async (r) => {
    if (r.request().method() === "POST") {
      const b = r.request().postDataJSON() as { url: string; events: string[] };
      if (b.url.startsWith("http://")) return r.fulfill({ status: 422, json: { detail: "Webhook addresses must start with https://.", code: "https_required", field: "url" } });
      const e = ep(`w${eps.length + 1}`, b.url, true, b.events, { last_delivery: null });
      eps.unshift(e);
      return r.fulfill({ status: 201, json: { ...e, secret: "whsec_SECRETSECRETSECRETSECRETSECRETSECRET", notice: "Copy the signing secret now." } });
    }
    return r.fulfill({ json: { entitled: opts.entitled ?? true, switched_off: opts.switchedOff ?? false, upgrade_url: "/org#plan", max_endpoints: 5, events: EVENTS, endpoints: eps } });
  });
  await page.route("**/api/org/webhooks/deliveries/*/retry", (r) => { calls.push("retry"); return r.fulfill({ status: 202, json: { delivery_id: "d2" } }); });
  await page.route("**/api/org/webhooks/*/deliveries", (r) => r.fulfill({ json: [delivery("d1", "SENT"), delivery("d2", "ABANDONED", "HTTP 500")] }));
  await page.route("**/api/org/webhooks/*/test", (r) => { calls.push("test"); return r.fulfill({ status: 202, json: { delivery_id: "d3" } }); });
  await page.route("**/api/org/webhooks/*/rotate-secret", (r) => { calls.push("rotate"); return r.fulfill({ json: { secret: "whsec_NEWSECRETNEWSECRETNEWSECRETNEWSECRE", secret_hint: "CRE", notice: "Copy the new signing secret now." } }); });
  await page.route(/\/api\/org\/webhooks\/w\d$/, (r) => {
    const id = r.request().url().split("/").pop()!;
    const i = eps.findIndex((x) => x.id === id);
    if (r.request().method() === "DELETE") { eps.splice(i, 1); calls.push("delete"); return r.fulfill({ status: 204, body: "" }); }
    const b = r.request().postDataJSON() as { enabled?: boolean };
    const e = eps[i]!;
    if (b.enabled !== undefined) { e.enabled = b.enabled; e.disabled_reason = b.enabled ? null : "Switched off by an administrator."; calls.push(b.enabled ? "on" : "off"); }
    return r.fulfill({ json: e });
  });
  return { calls };
}
