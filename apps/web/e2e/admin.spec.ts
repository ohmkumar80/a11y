import AxeBuilder from "@axe-core/playwright";
import { expect, mockApi, test } from "./fixtures";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];

async function audit(page: import("@playwright/test").Page, what: string) {
  const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  expect(results.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(" | ")})`), what).toEqual([]);
}

for (const scheme of ["light", "dark"] as const) {
  test(`axe: every admin tab, including generated settings forms (${scheme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await mockApi(page, "SUPER_ADMIN");
    await page.goto("/admin");
    await expect(page.getByRole("heading", { level: 1, name: "Admin" })).toBeVisible();
    await expect(page.getByRole("row", { name: /Acme Ltd/ })).toBeVisible();
    await audit(page, "organisations tab");

    await page.getByRole("tab", { name: "Plans" }).click();
    await expect(page.getByRole("row", { name: /Growth/ })).toBeVisible();
    await audit(page, "plans tab");

    await page.getByRole("tab", { name: "Coupons" }).click();
    await expect(page.getByRole("row", { name: /WELCOME20/ })).toBeVisible();
    await audit(page, "coupons tab");

    await page.getByRole("tab", { name: "Settings" }).click();
    for (const key of ["billing.trial", "ai.providers"]) {
      await page.getByRole("button", { name: /Setting$/ }).click();
      await page.getByRole("option", { name: new RegExp(key.replace(".", "\\.")) }).click();
      await expect(page.getByText("Current value comes from: global (v2)")).toBeVisible();
      await audit(page, `settings form ${key}`);
    }
    // The secret is write-only: the form shows only that one is set, never the value.
    await expect(page.getByLabel("Api key")).toHaveValue("");
    await expect(page.getByText(/ends in ab12/)).toBeVisible();
  });
}

test("org page shows seats, quota meters and the plan; meters are named and valued", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await page.goto("/org");
  await expect(page.getByRole("heading", { name: "Plan and usage" })).toBeVisible();
  const seats = page.getByRole("meter", { name: "Seats" });
  await expect(seats).toHaveAttribute("aria-valuetext", "3 of 3 seats");
  await expect(page.getByText("(nearly full)").first()).toBeVisible(); // warning is text, not colour alone
  await expect(page.getByRole("meter", { name: "Website scans this month" })).toHaveAttribute("aria-valuetext", "4 of 10");
  await expect(page.getByText("Unlimited on your plan")).toBeVisible();
  await audit(page, "org plan panel");
});

test("admin tabs are keyboard operable", async ({ page }) => {
  await mockApi(page, "SUPER_ADMIN");
  await page.goto("/admin");
  await page.getByRole("tab", { name: "Organisations" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Plans" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("tab", { name: "Plans", selected: true })).toBeVisible();
});

test("a never-set setting shows its built-in defaults in the form (not empty values)", async ({ page }) => {
  await mockApi(page, "SUPER_ADMIN");
  // Registered after mockApi, so it wins for this URL.
  await page.route("**/api/admin/settings/billing.trial?*", (r) =>
    r.fulfill({ json: { key: "billing.trial", source: "default", version: null, value: { length_days: 14, plan_id: "TRIAL", grace_days: 0, after_expiry: "LOCKED_READ_ONLY", reminder_days_before: [3, 1] } } }),
  );
  await page.goto("/admin");
  await page.getByRole("tab", { name: "Settings" }).click();
  await page.getByRole("button", { name: /Setting$/ }).click();
  await page.getByRole("option", { name: /billing\.trial/ }).click();
  await expect(page.getByText("Current value comes from: default")).toBeVisible();
  await expect(page.getByLabel("Reminder days before")).toHaveValue("3, 1");
  await expect(page.getByLabel("Length days")).toHaveValue("14");
});
