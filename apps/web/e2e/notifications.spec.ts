import AxeBuilder from "@axe-core/playwright";
import { expect, mockApi, test } from "./fixtures";
import { mockNotifications } from "./notification-mocks";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];
async function audit(page: import("@playwright/test").Page, what: string) {
  const r = await new AxeBuilder({ page }).withTags(TAGS).exclude("[data-live-announcer]").analyze();
  expect(r.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(" | ")})`), what).toEqual([]);
}

for (const scheme of ["light", "dark"] as const) {
  test(`notification centre: unread count, list, marking read, email choice (${scheme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await mockApi(page, "STANDARD_USER");
    const { calls } = await mockNotifications(page);
    await page.goto("/notifications");
    // the header link says how many are unread, in words as well as a number
    await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: /Notifications.*2 unread/ })).toBeVisible();
    await expect(page.getByText("2 unread.", { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { level: 3, name: /Your accessibility scan of https:\/\/example\.com\/ is ready/ })).toBeVisible();
    await expect(page.getByText("Unread", { exact: true })).toHaveCount(2); // unread is a word, not only a colour or weight
    await audit(page, "notifications: list");

    await page.getByRole("button", { name: /Mark as read\s*: You have used all your scans/ }).click();
    await expect(page.getByText("1 unread.", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Mark all as read" }).click();
    await expect(page.getByText("All notifications are marked as read.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Mark all as read" })).toHaveCount(0);
    expect(calls).toEqual(["read:n2", "read-all"]);

    const box = page.getByRole("checkbox", { name: "Email me when a scan finishes or fails" });
    await expect(box).toBeChecked();
    await page.getByText("Email me when a scan finishes or fails").click();
    await expect(page.getByText("You will not get scan emails.")).toBeVisible();
    await expect(box).not.toBeChecked();
    expect(calls).toContain("prefs:false");
    await audit(page, "notifications: all read");
  });
}

test("an empty centre explains itself", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await mockNotifications(page, { empty: true });
  await page.goto("/notifications");
  await expect(page.getByText(/You have no notifications yet/)).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Notifications" })).toBeVisible(); // no badge when nothing is unread
});

test("following a notification marks it read and opens the page", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  const { calls } = await mockNotifications(page);
  await page.goto("/notifications");
  await page.getByRole("link", { name: /You have used all your scans this month/ }).click();
  await expect(page).toHaveURL(/\/org/);
  expect(calls).toContain("read:n2");
});

test("the link is left out when the centre is switched off, and for platform administrators", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await page.route("**/api/org/flags", (r) => r.fulfill({ json: { public_api: true, webhooks: true, vpat: true, crawl_scans: true, notification_center: false } }));
  await page.goto("/workspace");
  await expect(page.getByRole("link", { name: /^Notifications/ })).toHaveCount(0);
  const admin = await page.context().newPage();
  await mockApi(admin, "SUPER_ADMIN");
  await admin.goto("/admin");
  await expect(admin.getByRole("link", { name: /^Notifications/ })).toHaveCount(0);
});

test("the header is the same on every page with the link last before Help", async ({ page }) => {
  await mockApi(page, "STANDARD_USER");
  await page.goto("/workspace");
  const links = await page.getByRole("navigation", { name: "Main" }).getByRole("link").allInnerTexts();
  expect(links.at(-1)).toBe("Help"); // SC 3.2.6: help stays in the same last place
  expect(links.some((t) => t.startsWith("Notifications"))).toBe(true);
});
