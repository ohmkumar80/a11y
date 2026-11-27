import AxeBuilder from "@axe-core/playwright";
import { expect, mockApi, test } from "./fixtures";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];
async function audit(page: import("@playwright/test").Page, what: string) {
  const r = await new AxeBuilder({ page }).withTags(TAGS).exclude("[data-live-announcer]").analyze();
  expect(r.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(" | ")})`), what).toEqual([]);
}

for (const scheme of ["light", "dark"] as const) {
  test(`the API reference renders every operation accessibly (${scheme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await mockApi(page, "ANON");
    await page.goto("/developers");
    await expect(page.getByRole("heading", { level: 1, name: "API reference" })).toBeVisible();
    await expect(page.getByRole("heading", { level: 2, name: /Overview/ })).toBeVisible();
    await expect(page.getByText(/never a statement of conformance/)).toBeVisible();
    // one heading per operation, with a table of contents link to each
    for (const summary of ["Start a scan", "List a scan's findings", "Create a report", "Download a finished report", "Read the organisation's audit log"]) {
      await expect(page.getByRole("heading", { level: 3, name: new RegExp(summary) })).toBeVisible();
      await expect(page.getByRole("navigation", { name: "API sections" }).getByRole("link", { name: summary })).toBeVisible();
    }
    const start = page.getByRole("region", { name: /Start a scan/ });
    await expect(start.getByRole("table", { name: /Request body \(ScanIn\)/ })).toBeVisible();
    await expect(start.getByRole("rowheader", { name: "url" })).toBeVisible();
    await expect(start.getByText(/Idempotency-Key/).first()).toBeVisible();
    await expect(start.getByText(/Authorization: Bearer \$A11Y_API_KEY/)).toBeVisible();
    await expect(start.getByText("Required scope:", { exact: false })).toBeVisible();
    await audit(page, "api reference");
  });
}

test("the table of contents moves to the section (keyboard)", async ({ page }) => {
  await mockApi(page, "ANON");
  await page.goto("/developers");
  await page.getByRole("navigation", { name: "API sections" }).getByRole("link", { name: "Start a scan" }).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#op-create_scan/);
});

test("a failure to load the description is explained", async ({ page }) => {
  await mockApi(page, "ANON");
  await page.route("**/api/v1/openapi.json", (r) => r.fulfill({ status: 500, body: "" }));
  await page.goto("/developers");
  await expect(page.getByText("The API description could not be loaded.")).toBeVisible();
});
