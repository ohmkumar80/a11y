import AxeBuilder from "@axe-core/playwright";
import { opsState } from "./admin-mocks";
import { expect, mockApi, test } from "./fixtures";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];
async function audit(page: import("@playwright/test").Page, what: string) {
  const r = await new AxeBuilder({ page }).withTags(TAGS).exclude("[data-live-announcer]").analyze();
  expect(r.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(" | ")})`), what).toEqual([]);
}

for (const scheme of ["light", "dark"] as const) {
  test(`operations: status, incidents with runbooks, canaries and queues (${scheme})`, async ({ page }) => {
    opsState.healthy = false;
    await page.emulateMedia({ colorScheme: scheme });
    await mockApi(page, "SUPER_ADMIN");
    await page.goto("/admin");
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Operations", exact: true }).click();
    await expect(page.getByRole("heading", { level: 2, name: /There are problems that need attention/ })).toBeVisible();
    const inc = page.getByRole("grid", { name: "Incidents" });
    await expect(inc.getByRole("row", { name: /Scans are stuck/ })).toContainText("Critical"); // severity is a word, not a colour
    await expect(inc.getByRole("row", { name: /platform reasons/ })).toContainText("system_error: 2, worker_lost: 1");
    await expect(inc.getByRole("row", { name: /given up on/ })).toContainText("For information");
    const cans = page.getByRole("grid", { name: "Canaries" });
    await expect(cans.getByRole("row", { name: /PDF generation/ })).toContainText("Failing");
    await expect(cans.getByRole("row", { name: /Mail server/ })).toContainText("Has not reported yet");
    await expect(page.getByText("Jobs waiting in the docs queue")).toBeVisible();
    await audit(page, "operations: problems");

    await inc.getByRole("button", { name: /Runbook for Scans are stuck/ }).click();
    const dialog = page.getByRole("dialog", { name: "Runbook: Scans are stuck" });
    await expect(dialog.getByRole("heading", { name: "Stuck scans" })).toBeVisible();
    await expect(dialog.getByRole("heading", { name: "Escalate" })).toBeVisible();
    await expect(dialog.getByRole("listitem").filter({ hasText: "Restart the scheduler" })).toBeVisible();
    await expect(dialog.locator("code").filter({ hasText: "docker compose restart beat" })).toBeVisible();
    await audit(page, "operations: runbook");
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
  });
}

test("a healthy platform says so plainly", async ({ page }) => {
  opsState.healthy = true;
  await mockApi(page, "SUPER_ADMIN");
  await page.goto("/admin");
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Operations", exact: true }).click();
  await expect(page.getByRole("heading", { level: 2, name: /All systems are working/ })).toBeVisible();
  await expect(page.getByText(/No incidents/)).toBeVisible();
  opsState.healthy = false;
});

test("refreshing reloads the numbers", async ({ page }) => {
  opsState.healthy = false;
  await mockApi(page, "SUPER_ADMIN");
  await page.goto("/admin");
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Operations", exact: true }).click();
  await expect(page.getByRole("heading", { level: 2, name: /problems that need attention/ })).toBeVisible();
  opsState.healthy = true;
  await page.getByRole("button", { name: "Refresh" }).click();
  await expect(page.getByRole("heading", { level: 2, name: /All systems are working/ })).toBeVisible();
  opsState.healthy = false;
});
