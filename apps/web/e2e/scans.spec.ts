import AxeBuilder from "@axe-core/playwright";
import { expect, mockApi, test } from "./fixtures";
import { FIX_NO_MODEL, FIX_READY, SCAN_ID, mockFixApi, mockScanApi } from "./scan-mocks";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];
async function audit(page: import("@playwright/test").Page, what: string) {
  const r = await new AxeBuilder({ page }).withTags(TAGS).exclude("[data-live-announcer]").analyze();
  expect(r.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(" | ")})`), what).toEqual([]);
}

for (const scheme of ["light", "dark"] as const) {
  test(`workspace: new scan form, scans table, sites panel (${scheme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await mockApi(page, "COMPANY_ADMIN");
    await page.goto("/workspace");
    await expect(page.getByRole("heading", { name: "New scan" })).toBeVisible();
    await expect(page.getByRole("row", { name: /shop\.example\.com/ })).toBeVisible();
    await expect(page.getByRole("checkbox", { name: /WCAG 2\.2 Level AA: Reference standard/ })).toBeChecked();
    await expect(page.getByRole("checkbox", { name: /ADA Title III.*Benchmark \(not a legal requirement\)/ })).not.toBeChecked();
    await audit(page, "workspace");
    await page.getByLabel("Scan", { exact: true }).click();
    await page.getByRole("option", { name: /pages it links to/ }).click();
    await expect(page.getByLabel("Most pages to scan")).toBeVisible();
    await audit(page, "workspace crawl mode");
  });

  test(`scan results: summary, findings, grouped view, details dialog (${scheme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await mockApi(page, "COMPANY_ADMIN");
    await page.goto(`/workspace/scan?id=${SCAN_ID}`);
    await expect(page.getByRole("heading", { level: 2, name: "Summary" })).toBeVisible();
    await expect(page.getByText(/Automated checks exist for 30 of 55 criteria/)).toBeVisible();
    await expect(page.getByText(/not a statement of conformance/)).toBeVisible();
    await expect(page.getByText(/awaiting expert review/)).toBeVisible();
    await expect(page.getByRole("row", { name: /Images need a text alternative/ })).toBeVisible();
    await audit(page, "results");
    await page.getByRole("button", { name: /Group by/ }).click();
    await page.getByRole("option", { name: /Root cause/ }).click();
    await expect(page.getByText("40 on 12 pages")).toBeVisible();
    await audit(page, "results grouped");
    await page.getByRole("button", { name: /Group by/ }).click();
    await page.getByRole("option", { name: "Each occurrence" }).click();
    await page.getByRole("button", { name: /Details for Images need a text alternative/ }).click();
    const dialog = page.getByRole("dialog", { name: "Images need a text alternative" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText('<img src="logo.png">')).toBeVisible();
    await expect(dialog.getByRole("heading", { level: 3, name: "How to fix this" })).toBeVisible();
    await expect(dialog.getByText("awaiting expert review")).toBeVisible();
    await expect(dialog.getByRole("heading", { name: "Example in React (JSX)" })).toBeVisible();
    await expect(dialog.getByRole("link", { name: /1\.1\.1 Non-text Content/ })).toHaveAttribute("href", /w3\.org/);
    await audit(page, "details dialog");
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(page.getByRole("button", { name: /Details for Images need a text alternative/ })).toBeFocused(); // focus returns to the trigger
  });
}

test("a running scan shows progress and one polite status message, not a flood", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await mockScanApi(page, { status: "RUNNING" });
  await page.goto(`/workspace/scan?id=${SCAN_ID}`);
  await expect(page.getByRole("progressbar", { name: "Scan progress" })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "Scanning:" })).toHaveCount(1);
  await expect(page.getByRole("heading", { name: "Findings" })).toHaveCount(0); // no results until done
  await audit(page, "running scan");
});

test("a failed scan explains why and what to do", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await page.route(`**/api/scans/${SCAN_ID}**`, (r) => r.fulfill({ json: { id: SCAN_ID, url: "https://nope.example/", mode: "single", max_pages: 1, standards: ["WCAG_2_2_AA"], status: "FAILED", error_code: "dns_failed", error_detail: "We could not find nope.example. Check the address.", pages_scanned: 0, findings_count: 0, created_at: "2026-11-27T01:00:00Z", started_at: null, finished_at: null, engine_versions: {}, rules_version: null, attempts: 1, pages: [], by_kind: {}, summary: { standard: "WCAG_2_2_AA", label: "x", legal_status: "reference", citation: null, notes: null, automated_coverage: { tested: 0, total: 1 }, failed: [], needs_review: [], no_issues_found: [], not_tested: [], review_status: "draft", disclaimer: "" } } }));
  await page.goto(`/workspace/scan?id=${SCAN_ID}`);
  await expect(page.getByText("We could not find nope.example. Check the address.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Start a new scan" })).toBeVisible();
  await audit(page, "failed scan");
});

test("SSRF and validation errors land on the address field with an error summary", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await page.route("**/api/scans", (r) => r.request().method() === "POST"
    ? r.fulfill({ status: 422, json: { detail: "That address points to a private or internal network, which cannot be scanned.", field: "url", code: "private_address" } })
    : r.fulfill({ json: { total: 0, scans: [] } }));
  await page.goto("/workspace");
  await page.getByLabel("Web address").fill("http://169.254.169.254/");
  await page.getByRole("button", { name: "Start scan" }).click();
  const summary = page.getByRole("alert").filter({ hasText: "There is a problem" });
  await expect(summary).toBeFocused();
  await expect(summary.getByRole("link", { name: /private or internal network/ })).toBeVisible();
  await expect(page.getByLabel("Web address")).toHaveAttribute("aria-invalid", "true");
  await audit(page, "form error state");
});

test("quota and verification errors offer a next step", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await page.route("**/api/scans", (r) => r.request().method() === "POST"
    ? r.fulfill({ status: 402, json: { detail: "You have used 10 of 10 this month. Upgrade your plan for more.", code: "quota_exceeded", field: null } })
    : r.fulfill({ json: { total: 0, scans: [] } }));
  await page.goto("/workspace");
  await page.getByLabel("Web address").fill("https://example.com");
  await page.getByRole("button", { name: "Start scan" }).click();
  await expect(page.getByRole("link", { name: "See your plan" })).toBeVisible();
});

test("standard member can scan but does not see site verification", async ({ page }) => {
  await mockApi(page, "STANDARD_USER");
  await page.goto("/workspace");
  await expect(page.getByRole("heading", { name: "New scan" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Verified sites" })).toHaveCount(0);
});

for (const scheme of ["light", "dark"] as const) {
  test(`a checked code fix appears, is announced once, and can be copied (${scheme})`, async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await page.emulateMedia({ colorScheme: scheme });
    await mockApi(page, "COMPANY_ADMIN");
    await mockFixApi(page, FIX_READY);
    await page.goto(`/workspace/scan?id=${SCAN_ID}`);
    await page.getByRole("button", { name: /Group by/ }).click();
    await page.getByRole("option", { name: "Each occurrence" }).click();
    await page.getByRole("button", { name: /Details for Images need a text alternative/ }).click();
    const dialog = page.getByRole("dialog", { name: "Images need a text alternative" });
    await expect(dialog.getByRole("heading", { level: 3, name: "Suggested code fix" })).toBeVisible();
    await expect(dialog.getByText(/sends only this element/)).toBeVisible(); // the data use is stated before the click
    await audit(page, "fix: before asking");
    await dialog.getByRole("button", { name: "Suggest a fix" }).click();
    await expect(dialog.getByText('<button aria-label="Close"></button>')).toBeVisible();
    await expect(dialog.getByRole("status").filter({ hasText: "A checked fix is ready." })).toHaveCount(1);
    await expect(dialog.getByText("Suggested by an AI model")).toBeVisible();
    await expect(dialog.getByText("The problem no longer appears in our checks")).toBeVisible();
    await expect(dialog.getByText(/do not prove the page is accessible/)).toBeVisible();
    await expect(dialog.getByText("Written by an AI model: read it before you use it.")).toBeVisible();
    await audit(page, "fix: ready");
    await dialog.getByRole("button", { name: "Copy fix" }).click();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('<button aria-label="Close"></button>');
  });
}

test("when no fix can be trusted we say why and offer a retry, never code", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await mockFixApi(page, FIX_NO_MODEL, FIX_READY);
  await page.goto(`/workspace/scan?id=${SCAN_ID}`);
  await page.getByRole("button", { name: /Group by/ }).click();
  await page.getByRole("option", { name: "Each occurrence" }).click();
  await page.getByRole("button", { name: /Details for Images need a text alternative/ }).click();
  const dialog = page.getByRole("dialog", { name: "Images need a text alternative" });
  await dialog.getByRole("button", { name: "Suggest a fix" }).click();
  await expect(dialog.getByText(/No AI model is available/)).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Copy fix" })).toHaveCount(0);
  await audit(page, "fix: needs review");
  await dialog.getByRole("button", { name: "Try again" }).click();
  await expect(dialog.getByText('<button aria-label="Close"></button>')).toBeVisible();
});

test("a refused request (rate limit or switched off) is explained in words", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await mockScanApi(page);
  await page.route(`**/api/scans/${SCAN_ID}/findings/*/fix`, (r) => r.fulfill({ status: 403, json: { detail: "Fix suggestions are turned off for your account.", code: "fixes_disabled" } }));
  await page.goto(`/workspace/scan?id=${SCAN_ID}`);
  await page.getByRole("button", { name: /Group by/ }).click();
  await page.getByRole("option", { name: "Each occurrence" }).click();
  await page.getByRole("button", { name: /Details for Images need a text alternative/ }).click();
  const dialog = page.getByRole("dialog", { name: "Images need a text alternative" });
  await dialog.getByRole("button", { name: "Suggest a fix" }).click();
  await expect(dialog.getByText("Fix suggestions are turned off for your account.")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Suggest a fix" })).toBeVisible(); // can try again later
});

test("features an administrator switched off are not offered", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await page.route("**/api/org/flags", (r) => r.fulfill({ json: { public_api: true, webhooks: true, vpat: false, crawl_scans: false, notification_center: true } }));
  await page.goto("/workspace");
  await expect(page.getByRole("heading", { name: "New scan" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Scan/ }).filter({ hasText: "This page only" })).toHaveCount(0); // no crawl choice
  await page.goto(`/workspace/scan?id=${SCAN_ID}`);
  await expect(page.getByRole("heading", { level: 2, name: "Summary" })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Accessibility Conformance Report/ })).toHaveCount(0);
});
