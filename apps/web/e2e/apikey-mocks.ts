import type { Page } from "@playwright/test";

export const SCOPES = {
  "scans:read": "List scans and read their results and findings",
  "scans:write": "Start scans (uses scan credits)",
  "reports:read": "List and download reports",
  "reports:write": "Create reports",
  "audit:read": "Read your organisation's audit log",
};
const key = (id: string, name: string, hint: string, state: string, scopes: string[]) => ({
  id, name, hint, scopes, state, created_at: "2026-11-20T00:00:00Z", expires_at: "2027-02-18T00:00:00Z",
  last_used_at: state === "active" ? "2026-11-27T01:00:00Z" : null, revoked_at: state === "revoked" ? "2026-11-25T00:00:00Z" : null,
});

/** A small stateful fake of /org/api-keys: create adds a row, revoke marks one revoked. */
export async function mockApiKeys(page: Page, opts: { entitled?: boolean; max?: number } = {}) {
  const keys = [key("k1", "Build pipeline", "x9Qa", "active", ["scans:read", "scans:write"]), key("k2", "Old script", "Pz31", "revoked", ["scans:read"])];
  const bodies: unknown[] = [];
  await page.route("**/api/org/api-keys", async (r) => {
    if (r.request().method() === "POST") {
      const b = r.request().postDataJSON() as { name: string; scopes: string[]; expires_in_days: number | null };
      bodies.push(b);
      if (b.name === "boom") return r.fulfill({ status: 409, json: { detail: "You already have 10 active keys, the most your organisation can have. Revoke one first.", code: "too_many_keys" } });
      const k = key(`k${keys.length + 1}`, b.name, "AbCd", "active", b.scopes);
      keys.unshift(k);
      return r.fulfill({ status: 201, json: { ...k, key: "a11y_22222222222242228222222222222222_SECRETSECRETSECRETSECRETSECRETSECRETabc", notice: "Copy this key now." } });
    }
    return r.fulfill({ json: { entitled: opts.entitled ?? true, upgrade_url: "/org#plan", max_keys: opts.max ?? 10, max_lifetime_days: null, scopes: SCOPES, keys } });
  });
  await page.route("**/api/org/api-keys/*", (r) => {
    const id = r.request().url().split("/").pop()!;
    const k = keys.find((x) => x.id === id);
    if (k) { k.state = "revoked"; k.revoked_at = "2026-11-27T05:00:00Z"; }
    return r.fulfill({ status: 204, body: "" });
  });
  return { bodies };
}
