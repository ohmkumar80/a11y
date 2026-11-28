import AxeBuilder from "@axe-core/playwright";
import { expect, mockApi, test } from "./fixtures";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];
async function audit(page: import("@playwright/test").Page, what: string) {
  const r = await new AxeBuilder({ page }).withTags(TAGS).exclude("[data-live-announcer]").analyze();
  expect(r.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(" | ")})`), what).toEqual([]);
}

for (const scheme of ["light", "dark"] as const) {
  test(`emails tab: events, editor, draft preview and delivery log (${scheme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await mockApi(page, "SUPER_ADMIN");
    await page.goto("/admin");
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Emails", exact: true }).click();
    await expect(page.getByRole("grid", { name: "Emails the platform sends" }).getByRole("row", { name: /Scan finished/ })).toBeVisible();
    await expect(page.getByRole("grid", { name: /Recent emails/ }).getByRole("row", { name: /Monthly scan limit reached/ })).toBeVisible(); // delivery log
    await expect(page.getByText(/Failed: ConnectionError: smtp down/)).toBeVisible();
    await audit(page, "emails: list");

    await page.getByRole("button", { name: /Edit Scan finished/ }).click();
    const h = page.getByRole("heading", { level: 2, name: "Edit: Scan finished" });
    await expect(h).toBeFocused();
    await expect(page.getByText("{summary}").first()).toBeVisible(); // the allowed variables are listed
    await page.getByLabel("Subject").fill("All done: {url}");
    await page.getByLabel("Link text").fill("Open the results");
    await page.getByRole("button", { name: "Preview this draft" }).click();
    await expect(page.getByRole("heading", { level: 3, name: "Preview with sample data" })).toBeVisible();
    await expect(page.getByText("Accessibility check: passed.")).toBeVisible();
    const frame = page.frameLocator('iframe[title^="Preview of the email"]');
    await expect(frame.getByRole("heading", { name: "Open the results" })).toBeVisible();
    await audit(page, "emails: editing with preview");
  });
}

test("a bad placeholder is explained, not saved", async ({ page }) => {
  await mockApi(page, "SUPER_ADMIN");
  await page.goto("/admin");
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Emails", exact: true }).click();
  await page.getByRole("button", { name: /Edit Scan finished/ }).click();
  await page.getByLabel("Subject").fill("Hi {nope}");
  await page.getByRole("button", { name: "Preview this draft" }).click();
  await expect(page.getByText(/{nope} is not available here. You can use:/)).toBeVisible();
});

test("a required email cannot be switched off, and a test goes to the admin", async ({ page }) => {
  await mockApi(page, "SUPER_ADMIN");
  await page.goto("/admin");
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Emails", exact: true }).click();
  await page.getByRole("button", { name: /Edit Reset password/ }).click();
  await expect(page.getByRole("checkbox", { name: /Send this email \(always on/ })).toBeDisabled();
  await page.getByRole("button", { name: /Send a test to me.*Scan finished/ }).click();
  await expect(page.getByText("A test of “Scan finished” was sent to ops@example.com.")).toBeVisible();
});

test("saving requires a reason and publishes the whole list through the settings path", async ({ page }) => {
  await mockApi(page, "SUPER_ADMIN");
  let sent: { value: { items: Array<{ event: string; subject: string }> }; comment: string; publish: boolean } | null = null;
  await page.route("**/api/admin/settings/notify.templates", (r) => {
    if (r.request().method() === "PUT") { sent = r.request().postDataJSON(); return r.fulfill({ json: {} }); }
    return r.fulfill({ json: { key: "notify.templates", source: "default", version: null, value: { items: [] } } });
  });
  await page.goto("/admin");
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Emails", exact: true }).click();
  await page.getByRole("button", { name: /Edit Scan finished/ }).click();
  await page.getByLabel("Subject").fill("All done: {url}");
  await page.getByLabel("Why are you changing it?").fill("Friendlier wording");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("heading", { name: /Edit: Scan finished/ })).toHaveCount(0);
  expect(sent!.publish).toBe(true);
  expect(sent!.comment).toBe("Friendlier wording");
  expect(sent!.value.items).toEqual([expect.objectContaining({ event: "scan.completed", subject: "All done: {url}", enabled: true })]);
});
