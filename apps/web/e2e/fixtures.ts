import { test as base, type Page } from "@playwright/test";
import { BYOK, SUBSCRIPTION, mockAdminApi } from "./admin-mocks";
import openapi from "./openapi-fixture.json" with { type: "json" };
import { mockApiKeys } from "./apikey-mocks";
import { mockReportApi } from "./report-mocks";
import { mockScanApi } from "./scan-mocks";

export type Role = "ANON" | "COMPANY_ADMIN" | "STANDARD_USER" | "SUPER_ADMIN";

const user = (role: Exclude<Role, "ANON">) => ({
  id: "11111111-1111-4111-8111-111111111111",
  email: `${role.toLowerCase()}@example.com`,
  role,
  organization_id: "22222222-2222-4222-8222-222222222222",
  organization_name: "Example Org",
});

/** Pretend the API is up and the visitor has the given role. No real backend needed. */
export async function mockApi(page: Page, role: Role) {
  await page.route("**/api/auth/refresh", (r) =>
    role === "ANON"
      ? r.fulfill({ status: 401, json: { detail: "Session expired. Log in again." } })
      : r.fulfill({ json: { access_token: "t", token_type: "bearer", expires_in: 900, user: user(role) } }),
  );
  await page.route("**/api/org/users", (r) =>
    r.fulfill({ json: [user("COMPANY_ADMIN"), { ...user("STANDARD_USER"), id: "33333333-3333-4333-8333-333333333333", email: "member@example.com" }] }),
  );
  await page.route("**/api/org/subscription", (r) => r.fulfill({ json: SUBSCRIPTION }));
  await page.route("**/api/org/ai", (r) => r.fulfill({ json: BYOK }));
  await page.route("**/api/org/ai/test", (r) => r.fulfill({ json: { ok: false, detail: "authentication failed (check the API key)" } }));
  await mockAdminApi(page);
  await page.route("**/api/auth/mfa/status", (r) => r.fulfill({ json: { enabled: false, mode: "optional", required: false, recovery_codes_left: 0, available: role === "COMPANY_ADMIN" || role === "SUPER_ADMIN" } }));
  await mockScanApi(page);
  await mockReportApi(page);
  await mockApiKeys(page);
  await page.route("**/api/v1/openapi.json", (r) => r.fulfill({ json: openapi }));
  await page.route("**/api/invites/**", (r) =>
    r.request().method() === "GET"
      ? r.fulfill({ json: { email: "invitee@example.com", organization_name: "Example Org" } })
      : r.fulfill({ status: 204, body: "" }),
  );
  await page.route("**/api/auth/verify-email", (r) => r.fulfill({ status: 204, body: "" }));
}

export const test = base;
export { expect } from "@playwright/test";
