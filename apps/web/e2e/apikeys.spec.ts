import AxeBuilder from "@axe-core/playwright";
import { mockApiKeys } from "./apikey-mocks";
import { expect, mockApi, test } from "./fixtures";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];
async function audit(page: import("@playwright/test").Page, what: string) {
  const r = await new AxeBuilder({ page }).withTags(TAGS).exclude("[data-live-announcer]").analyze();
  expect(r.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(" | ")})`), what).toEqual([]);
}

for (const scheme of ["light", "dark"] as const) {
  test(`api keys: list, create with one-time reveal, revoke with confirmation (${scheme})`, async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await page.emulateMedia({ colorScheme: scheme });
    await mockApi(page, "COMPANY_ADMIN");
    const { bodies } = await mockApiKeys(page);
    await page.goto("/org/api");
    await expect(page.getByRole("heading", { level: 1, name: "API keys" })).toBeVisible();
    await expect(page.getByRole("row", { name: /Build pipeline/ })).toBeVisible();
    await expect(page.getByText("1 of 10 active keys.")).toBeVisible();
    await audit(page, "api keys: list");

    await page.getByLabel("Name").fill("CI server");
    await page.getByText(/Start scans.*scans:write/).click(); // the visible label, as a person would
    await expect(page.getByRole("checkbox", { name: /Start scans/ })).toBeChecked();
    await page.getByRole("button", { name: "Create key" }).click();
    const h = page.getByRole("heading", { level: 2, name: /Your new key: copy it now/ });
    await expect(h).toBeFocused(); // focus moves to the one-time key
    await expect(page.getByText(/a11y_2222.*SECRETSECRET/)).toBeVisible();
    await expect(page.getByText(/only time the key is shown/)).toBeVisible();
    expect(bodies[0]).toEqual({ name: "CI server", scopes: ["scans:read", "scans:write"], expires_in_days: 90 });
    await audit(page, "api keys: one-time key");
    await page.getByRole("button", { name: "Copy key" }).click();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toMatch(/^a11y_2222/);
    await page.getByRole("button", { name: "I have stored it safely" }).click();
    await expect(h).toHaveCount(0); // the secret is gone from the page
    await expect(page.getByRole("row", { name: /CI server/ })).toBeVisible();

    await page.getByRole("button", { name: /Revoke key CI server/ }).click();
    const dialog = page.getByRole("dialog", { name: /Revoke “CI server”\?/ });
    await expect(dialog).toBeVisible();
    await audit(page, "api keys: revoke dialog");
    await dialog.getByRole("button", { name: "Revoke key" }).click();
    await expect(page.getByText("The key “CI server” was revoked. It stops working immediately.")).toBeVisible();
    await expect(page.getByRole("row", { name: /CI server/ })).toContainText("Revoked");
  });
}

test("a refused creation is explained next to the form", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await mockApiKeys(page);
  await page.goto("/org/api");
  await page.getByLabel("Name").fill("boom");
  await page.getByRole("button", { name: "Create key" }).click();
  await expect(page.getByText(/You already have 10 active keys/).first()).toBeVisible();
});

test("a key needs at least one permission", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await mockApiKeys(page);
  await page.goto("/org/api");
  await page.getByLabel("Name").fill("x");
  await page.getByText(/List scans and read/).click();
  await expect(page.getByRole("checkbox", { name: /List scans/ })).not.toBeChecked();
  await page.getByRole("button", { name: "Create key" }).click();
  await expect(page.getByText("Choose at least one permission.").first()).toBeVisible();
});

test("a plan without API access sees why, not a form", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await mockApiKeys(page, { entitled: false });
  await page.goto("/org/api");
  await expect(page.getByText(/API access is not part of your current plan/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Create key" })).toHaveCount(0);
});

test("members cannot manage keys", async ({ page }) => {
  await mockApi(page, "STANDARD_USER");
  await page.goto("/org/api");
  await expect(page.getByRole("button", { name: "Create key" })).toHaveCount(0);
});
