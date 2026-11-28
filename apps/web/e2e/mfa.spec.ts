import AxeBuilder from "@axe-core/playwright";
import { expect, mockApi, test } from "./fixtures";
import { mfaState } from "./admin-mocks";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];
async function audit(page: import("@playwright/test").Page, what: string) {
  const r = await new AxeBuilder({ page }).withTags(TAGS).exclude("[data-live-announcer]").analyze();
  expect(r.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(" | ")})`), what).toEqual([]);
}

const USER = { id: "11111111-1111-4111-8111-111111111111", email: "admin@example.com", role: "COMPANY_ADMIN", organization_id: "22222222-2222-4222-8222-222222222222", organization_name: "Example Org", mfa_enabled: true };
const SESSION = { access_token: "t", token_type: "bearer", expires_in: 900, user: USER };
const VERIFY = { mfa: "verify", mfa_token: "tok", expires_in: 600, issuer: "a11y" };
const ENROL = { mfa: "enroll", mfa_token: "tok", expires_in: 600, issuer: "a11y" };

async function signIn(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill("admin@example.com");
  await page.getByLabel("Password").fill("correct horse battery");
  await page.getByRole("button", { name: "Log in" }).click();
}

test.beforeEach(() => { mfaState.superAdmin = "required"; });

for (const scheme of ["light", "dark"] as const) {
  test(`code step: labelled, paste-friendly, recovery alternative (${scheme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await mockApi(page, "ANON");
    await page.route("**/api/auth/login", (r) => r.fulfill({ json: VERIFY }));
    await signIn(page);
    await expect(page.getByRole("heading", { level: 1, name: "Enter your verification code" })).toBeFocused();
    const code = page.getByLabel("6-digit code");
    await expect(code).toHaveAttribute("autocomplete", "one-time-code"); // SC 1.3.5 / 3.3.8: password managers and SMS autofill work
    await expect(code).toHaveAttribute("inputmode", "numeric");
    await expect(page.getByText(/You have 10 minutes to finish signing in/)).toBeVisible(); // SC 2.2.1: the limit is stated
    await audit(page, "code step");
    await page.getByRole("button", { name: "Use a recovery code instead" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Use a recovery code" })).toBeFocused();
    await audit(page, "recovery step");
  });

  test(`forced enrolment: text key, no QR-only, recovery codes saved before continuing (${scheme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await mockApi(page, "ANON");
    await page.route("**/api/auth/login", (r) => r.fulfill({ json: ENROL }));
    await page.route("**/api/auth/mfa/enroll/start", (r) => r.fulfill({ json: { key: "ABCD EFGH IJKL MNOP QRST UVWX YZ23 4567", otpauth_uri: "otpauth://totp/a11y:admin%40example.com?secret=ABCDEFGH", issuer: "a11y", account: "admin@example.com" } }));
    await page.route("**/api/auth/mfa/enroll/confirm", (r) => r.fulfill({ json: { ...SESSION, recovery_codes: ["abcde-fghjk", "mnpqr-stuvw", "xyz23-45678", "bcdef-ghjkm", "npqrs-tuvwx", "yz234-56789", "cdefg-hjkmn", "pqrst-uvwxy", "z2345-6789a", "defgh-jkmnp"] } }));
    await signIn(page);
    await expect(page.getByRole("heading", { level: 1, name: "Set up two-step verification" })).toBeFocused();
    await expect(page.getByText("ABCD EFGH IJKL MNOP QRST UVWX YZ23 4567")).toBeVisible();
    await expect(page.getByLabel(/Setup key: ABCD, EFGH/)).toBeVisible(); // read out in groups, not as one long string
    await expect(page.getByRole("link", { name: /Open in my authenticator app/ })).toHaveAttribute("href", /^otpauth:/);
    await expect(page.locator("img, canvas, svg[role=img]")).toHaveCount(0); // never QR-only
    await audit(page, "enrol step");
    await page.getByLabel("6-digit code").fill("123456");
    await page.getByRole("button", { name: "Turn on two-step verification" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Save your recovery codes" })).toBeFocused();
    await expect(page.getByRole("list", { name: "Recovery codes" }).getByRole("listitem")).toHaveCount(10);
    await expect(page.getByRole("button", { name: "Continue" })).toBeDisabled();
    await audit(page, "recovery codes");
    await page.getByText("I have saved these recovery codes").click();
    await expect(page.getByRole("button", { name: "Continue" })).toBeEnabled();
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page).toHaveURL(/\/workspace/);
  });
}

test("a wrong code puts focus on an error summary; the right code signs in", async ({ page }) => {
  await mockApi(page, "ANON");
  await page.route("**/api/auth/login", (r) => r.fulfill({ json: VERIFY }));
  let calls = 0;
  await page.route("**/api/auth/mfa/verify", (r) => {
    calls += 1;
    return calls === 1
      ? r.fulfill({ status: 422, json: { detail: "That code is not correct. Check the code in your authenticator app and try again.", field: "code" } })
      : r.fulfill({ json: SESSION });
  });
  await signIn(page);
  await page.getByLabel("6-digit code").fill("000000");
  await page.getByRole("button", { name: "Verify" }).click();
  const summary = page.getByRole("alert").filter({ hasText: "There is a problem" });
  await expect(summary).toBeFocused();
  await expect(page.getByLabel("6-digit code")).toHaveAttribute("aria-invalid", "true");
  await page.getByLabel("6-digit code").fill("123 456"); // pasted with a space
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page).toHaveURL(/\/workspace/);
});

test("a lockout and an expired sign-in are explained, with a way forward", async ({ page }) => {
  await mockApi(page, "ANON");
  await page.route("**/api/auth/login", (r) => r.fulfill({ json: VERIFY }));
  await page.route("**/api/auth/mfa/verify", (r) => r.fulfill({ status: 429, json: { detail: "Too many incorrect codes. Try again in 15 minutes.", code: "mfa_locked", field: "code" } }));
  await signIn(page);
  await page.getByLabel("6-digit code").fill("000000");
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "There is a problem" })).toContainText("Too many incorrect codes. Try again in 15 minutes.");
  await page.route("**/api/auth/mfa/verify", (r) => r.fulfill({ status: 401, json: { detail: "Your sign-in took too long. Sign in again.", code: "mfa_token_expired" } }));
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Sign in again" })).toBeVisible();
  await page.getByRole("button", { name: "Start again" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Log in" })).toBeVisible();
});

test.describe("narrow screens", () => {
  test.use({ viewport: { width: 320, height: 640 } });
  test("the sign-in steps reflow at 320px (SC 1.4.10)", async ({ page }) => {
    await mockApi(page, "ANON");
    await page.route("**/api/auth/login", (r) => r.fulfill({ json: ENROL }));
    await page.route("**/api/auth/mfa/enroll/start", (r) => r.fulfill({ json: { key: "ABCD EFGH IJKL MNOP QRST UVWX YZ23 4567", otpauth_uri: "otpauth://totp/a11y:x", issuer: "a11y", account: "a-very-long-administrator-address@some-long-domain.example.com" } }));
    await signIn(page);
    await expect(page.getByText("ABCD EFGH IJKL MNOP QRST UVWX YZ23 4567")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
  });
});

test("admin Security tab: change the policy, with a reason; off shows a warning and the banner", async ({ page }) => {
  await mockApi(page, "SUPER_ADMIN");
  let put: { value?: { super_admin?: string }; comment?: string } | null = null;
  await page.route("**/api/admin/settings/auth.mfa", async (r) => {
    if (r.request().method() === "PUT") { put = r.request().postDataJSON(); mfaState.superAdmin = (put?.value?.super_admin as "off") ?? "required"; return r.fulfill({ json: { version: 2, status: "published" } }); }
    return r.fallback();
  });
  await page.goto("/admin");
  await expect(page.getByText(/Two-step verification is OFF/)).toHaveCount(0);
  await page.getByRole("tab", { name: "Security" }).click();
  await expect(page.getByRole("heading", { name: "Two-step verification policy" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Save policy" })).toBeDisabled(); // nothing changed yet
  await audit(page, "security tab");
  await page.getByRole("button", { name: /Platform administrators/ }).click();
  await page.getByRole("option", { name: /Off: nobody is asked/ }).click();
  await expect(page.getByText(/anyone who knows an administrator's password can use the admin console/)).toBeVisible();
  await page.getByLabel(/Why are you changing this/).fill("Developing the scanner; MFA is in the way");
  await page.getByRole("button", { name: "Save policy" }).click();
  await expect(page.getByText("Policy saved")).toBeVisible();
  expect(put).toMatchObject({ value: { super_admin: "off" }, comment: "Developing the scanner; MFA is in the way" });
  await expect(page.getByText(/Two-step verification is OFF for platform administrators/)).toBeVisible(); // banner appears at once
  await audit(page, "security tab with banner");
});

test("the off banner is shown on every admin tab, not just Security", async ({ page }) => {
  mfaState.superAdmin = "off";
  await mockApi(page, "SUPER_ADMIN");
  await page.goto("/admin");
  await expect(page.getByText(/Two-step verification is OFF/)).toBeVisible();
  await page.getByRole("tab", { name: "Plans" }).click();
  await expect(page.getByText(/Two-step verification is OFF/)).toBeVisible();
  await audit(page, "banner on plans tab");
});

test("org admins see their own security section on the organisation page", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await page.goto("/org");
  await expect(page.getByRole("heading", { name: "Your security" })).toBeVisible();
  await expect(page.getByText(/Two-step verification: Off/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Set up two-step verification" })).toBeVisible();
  await audit(page, "org security section");
});
