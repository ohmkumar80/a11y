import AxeBuilder from "@axe-core/playwright";
import { expect, mockApi, test } from "./fixtures";
import { SCAN_ID, mockFixApi } from "./scan-mocks";
import { FIX_READY } from "./scan-mocks";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];
async function audit(page: import("@playwright/test").Page, what: string) {
  const r = await new AxeBuilder({ page }).withTags(TAGS).exclude("[data-live-announcer]").analyze();
  expect(r.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(" | ")})`), what).toEqual([]);
}
const URL = `/workspace/scan/workbench?id=${SCAN_ID}`;

for (const scheme of ["light", "dark"] as const) {
  test(`workbench: list, screenshot with the element outlined, guidance and fix (${scheme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await mockApi(page, "COMPANY_ADMIN");
    await mockFixApi(page, FIX_READY);
    await page.goto(URL);
    await expect(page.getByRole("heading", { level: 1, name: "Fix Workbench" })).toBeVisible();
    await expect(page.getByText("2 problems.")).toBeVisible();
    await expect(page.getByRole("heading", { level: 2, name: "Choose a problem" })).toBeVisible();
    await audit(page, "workbench: nothing chosen");

    const first = page.getByRole("button", { name: /Critical: Images need a text alternative/ });
    await first.click();
    const h = page.getByRole("heading", { level: 2, name: "Images need a text alternative" });
    await expect(h).toBeFocused(); // focus lands on what was chosen
    await expect(first).toHaveAttribute("aria-current", "true");
    const img = page.getByRole("img", { name: /Screenshot of https:\/\/example\.com\/, zoomed in on the element/ });
    await expect(img).toBeVisible();
    await expect(page.getByText("The outlined area is the element with the problem.")).toBeVisible();
    await expect(page.getByText(/Only the top 1000 pixels of this page \(2400 tall\)/)).toBeVisible();
    await expect(page.getByText('<img src="logo.png">')).toBeVisible(); // the same facts in words
    await expect(page.getByRole("heading", { level: 3, name: "How to fix this" })).toBeVisible();
    await expect(page.getByRole("heading", { level: 3, name: "Suggested code fix" })).toBeVisible();
    await audit(page, "workbench: problem chosen");

    await page.getByRole("button", { name: "Show the whole saved page" }).click();
    const region = page.getByRole("region", { name: /whole saved page/ });
    await expect(region).toBeVisible();
    await region.focus();
    await expect(region).toBeFocused(); // a scrollable area is reachable by keyboard
    await audit(page, "workbench: whole page");
  });
}

test("next and previous move through the list; a hidden element says so instead of drawing a box", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await page.goto(URL);
  await page.getByRole("button", { name: /Critical: Images need a text alternative/ }).click();
  await expect(page.getByRole("button", { name: "Previous problem" })).toBeDisabled();
  await page.getByRole("button", { name: "Next problem" }).click();
  await expect(page.getByRole("heading", { level: 2, name: "Buttons need a name" })).toBeFocused();
  await expect(page.getByText(/not visible on the page/)).toBeVisible();
  await expect(page.getByText("The outlined area is the element with the problem.")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Next problem" })).toBeDisabled();
  await page.getByRole("button", { name: "Back to the list" }).click();
  await expect(page.getByRole("button", { name: /Serious: Buttons need a name/ })).toBeFocused();
  await audit(page, "workbench: hidden element");
});

test("the workbench works with the keyboard alone", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await page.goto(URL);
  const item = page.getByRole("button", { name: /Critical: Images need a text alternative/ });
  await item.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { level: 2, name: "Images need a text alternative" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Next problem" })).toBeFocused();
});

test("a scan that has not finished sends people back", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  const { mockScanApi } = await import("./scan-mocks");
  await mockScanApi(page, { status: "RUNNING" });
  await page.goto(URL);
  await expect(page.getByText(/has not finished/)).toBeVisible();
});
