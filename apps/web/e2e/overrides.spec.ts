import AxeBuilder from "@axe-core/playwright";
import { overrideCalls } from "./admin-mocks";
import { expect, mockApi, test } from "./fixtures";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];
async function audit(page: import("@playwright/test").Page, what: string) {
  const r = await new AxeBuilder({ page }).withTags(TAGS).exclude("[data-live-announcer]").analyze();
  expect(r.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(" | ")})`), what).toEqual([]);
}

for (const scheme of ["light", "dark"] as const) {
  test(`exceptions for one organisation: list, add and remove with a reason (${scheme})`, async ({ page }) => {
    overrideCalls.length = 0;
    await page.emulateMedia({ colorScheme: scheme });
    await mockApi(page, "SUPER_ADMIN");
    await page.goto("/admin?tab=tenants");
    await page.getByRole("button", { name: /Exceptions for Acme Ltd/ }).click();
    const dialog = page.getByRole("dialog", { name: "Exceptions for Acme Ltd" });
    const table = dialog.getByRole("grid", { name: "Exceptions for this organisation" });
    await expect(table.getByRole("row", { name: /Website scans this month/ })).toContainText("On, up to 500");
    await expect(table.getByRole("row", { name: /Byok ai/i })).toContainText("On, no limit");
    await expect(dialog.getByText(/replaces what the plan says for this organisation only/)).toBeVisible();
    await audit(page, "exceptions: list");

    // removing needs a reason first
    const remove = table.getByRole("button", { name: /Remove the exception for Website scans/ });
    await expect(remove).toBeDisabled();
    await dialog.getByLabel("Reason").fill("Pilot ended");
    await expect(remove).toBeEnabled();
    await remove.click();
    await expect(dialog.getByText("The exception for Website scans this month was removed.")).toBeVisible();
    expect(overrideCalls).toContain("delete:urls_monthly:Pilot ended");

    await dialog.getByRole("button", { name: /Feature/ }).click();
    await page.getByRole("option", { name: "Seats" }).click();
    await dialog.getByLabel("Limit per month").fill("25");
    await dialog.getByLabel("Reason").fill("Agreed with the customer on 12 December");
    await dialog.getByRole("button", { name: "Save exception" }).click();
    await expect(dialog.getByText("The exception for Seats is saved.")).toBeVisible();
    expect(overrideCalls).toContain("put:seats");
    await audit(page, "exceptions: after saving");
  });
}

for (const scheme of ["light", "dark"] as const) {
  test(`coupon campaigns: batch creation shows codes once, with copy and CSV; switching a campaign off (${scheme})`, async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await page.emulateMedia({ colorScheme: scheme });
    await mockApi(page, "SUPER_ADMIN");
    await page.goto("/admin?tab=tenants");
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Coupons", exact: true }).click();
    const camps = page.getByRole("grid", { name: "Coupon campaigns" });
    await expect(camps.getByRole("row", { name: /Partner webinar/ })).toContainText("25");
    await expect(camps.getByRole("row", { name: /Old promo/ }).getByRole("button")).toHaveCount(0); // nothing left to switch off
    await audit(page, "campaigns: list");

    await page.getByRole("textbox", { name: "Campaign", exact: true }).fill("Webinar May");
    await page.getByRole("textbox", { name: "Prefix", exact: true }).fill("WEBINAR");
    await page.getByRole("textbox", { name: "Count", exact: true }).or(page.getByRole("spinbutton", { name: "Count", exact: true })).fill("5");
    await page.getByRole("button", { name: "Create codes" }).click();
    const codes = page.getByLabel(/5 codes for “Webinar May”/);
    await expect(codes).toHaveValue(/WEBINAR-AB0CDEFG\nWEBINAR-AB1CDEFG/);
    await audit(page, "campaigns: codes shown");
    await page.getByRole("button", { name: "Copy all codes" }).click();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toContain("WEBINAR-AB4CDEFG");
    const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Download as CSV" }).click()]);
    expect(download.suggestedFilename()).toBe("Webinar-May-codes.csv");
    await page.getByRole("button", { name: "I have saved them" }).click();
    await expect(codes).toHaveCount(0); // the codes are gone from the page

    await camps.getByRole("button", { name: /Switch off all codes in Partner webinar/ }).click();
    await expect(page.getByText("Every code in “Partner webinar” is switched off.")).toBeVisible();
  });
}

test("a duplicate campaign name is explained next to the field", async ({ page }) => {
  await mockApi(page, "SUPER_ADMIN");
  await page.goto("/admin?tab=tenants");
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Coupons", exact: true }).click();
  await page.getByRole("textbox", { name: "Campaign", exact: true }).fill("Duplicate");
  await page.getByRole("textbox", { name: "Prefix", exact: true }).fill("DUP");
  await page.getByRole("button", { name: "Create codes" }).click();
  await expect(page.getByText("A campaign with that name already exists. Choose another name.").first()).toBeVisible();
});
