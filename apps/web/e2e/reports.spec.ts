import AxeBuilder from "@axe-core/playwright";
import { expect, mockApi, test } from "./fixtures";
import { VPAT_ID, mockReportApi } from "./report-mocks";
import { SCAN_ID } from "./scan-mocks";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];
async function audit(page: import("@playwright/test").Page, what: string) {
  const r = await new AxeBuilder({ page }).withTags(TAGS).exclude("[data-live-announcer]").analyze();
  expect(r.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(" | ")})`), what).toEqual([]);
}

for (const scheme of ["light", "dark"] as const) {
  test(`scan results: reports panel and VPAT entry (${scheme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await mockApi(page, "COMPANY_ADMIN");
    await page.goto(`/workspace/scan?id=${SCAN_ID}`);
    await expect(page.getByRole("heading", { level: 2, name: "Reports" })).toBeVisible();
    await expect(page.getByRole("row", { name: "Audit report (PDF)" })).toContainText("Passed (veraPDF PDF/UA-1)");
    await expect(page.getByRole("row", { name: "Audit report (Word)" })).toContainText("Being prepared");
    await expect(page.getByRole("row", { name: "All findings (CSV)" })).toContainText("Failed: We could not produce a file");
    await expect(page.getByRole("row", { name: "VPAT (PDF)" })).toHaveCount(0); // VPAT exports are listed on the VPAT page only
    await expect(page.getByRole("heading", { name: "Accessibility Conformance Report (VPAT)" })).toBeVisible();
    await audit(page, "reports panel");
  });

  test(`VPAT draft: editor, tabs, sign-off form (${scheme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await mockApi(page, "COMPANY_ADMIN");
    await page.goto(`/workspace/vpat?id=${VPAT_ID}`);
    await expect(page.getByRole("heading", { level: 2, name: "Status" })).toBeVisible();
    await expect(page.getByText("2 of 3 criteria are still")).toBeVisible();
    await expect(page.getByText(/has not yet been signed off by an accessibility expert/)).toBeVisible();
    await expect(page.getByRole("row", { name: "WCAG 1.1.1 Non-text Content" })).toContainText("Automated: 4 failures on 3 of 3 pages");
    await audit(page, "vpat level A");
    await page.getByRole("tab", { name: "Level AA" }).click();
    await expect(page.getByRole("row", { name: "WCAG 1.2.5 Audio Description (Prerecorded)" })).toBeVisible();
    await audit(page, "vpat level AA");
  });
}

test("downloading a ready report saves a file and announces it", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await page.goto(`/workspace/scan?id=${SCAN_ID}`);
  const [dl] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: /Download Audit report \(PDF\)/ }).click(),
  ]);
  expect(dl.suggestedFilename()).toBe("a11y-audit-example.com-2026-11-27.pdf");
  await expect(page.getByRole("status").filter({ hasText: "Audit report (PDF) downloaded." })).toBeVisible();
});

test("requesting a report confirms it politely and keeps the page usable", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  let posted: unknown = null;
  await page.route(`**/api/scans/${SCAN_ID}/reports`, async (r, ) => {
    if (r.request().method() === "POST") { posted = r.request().postDataJSON(); return r.fulfill({ status: 202, json: { id: "r-new", status: "QUEUED", reused: false } }); }
    return r.fallback();
  });
  await page.goto(`/workspace/scan?id=${SCAN_ID}`);
  await page.getByRole("button", { name: "Create All findings (CSV)" }).click();
  await expect(page.getByText("Report requested")).toBeVisible();
  expect(posted).toEqual({ kind: "audit_csv", standard: "WCAG_2_2_AA" });
});

test("a remark is required for 'Partially Supports' and the error is announced in the summary", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await page.goto(`/workspace/vpat?id=${VPAT_ID}`);
  await page.getByRole("tab", { name: "Level AA" }).click();
  await page.getByRole("button", { name: /Conformance level for WCAG 1\.2\.5/ }).click();
  await page.getByRole("option", { name: "Partially Supports" }).click();
  await page.getByLabel(/Remarks for WCAG 1\.2\.5/).fill("");
  await page.getByRole("button", { name: "Save changes" }).click();
  const summary = page.getByRole("alert").filter({ hasText: "There is a problem" });
  await expect(summary).toBeFocused();
  await expect(summary).toContainText("explain why it is 'Partially Supports'");
});

test("sign-off needs the confirmation, then exports appear", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await page.goto(`/workspace/vpat?id=${VPAT_ID}`);
  await expect(page.getByRole("button", { name: "Sign off this VPAT" })).toBeDisabled();
  await page.getByLabel("Your full name").fill("Priya N");
  await page.getByLabel("Your role").fill("Accessibility lead");
  await page.getByText(/I have reviewed each conformance level/).click();
  await expect(page.getByRole("checkbox", { name: /I have reviewed each conformance level/ })).toBeChecked();
  await expect(page.getByRole("button", { name: "Sign off this VPAT" })).toBeEnabled();
  await audit(page, "sign-off form filled");
});

test("a signed-off VPAT shows who signed, its exports, and can be reopened", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await mockReportApi(page, { vpat: "SIGNED_OFF" });
  await page.goto(`/workspace/vpat?id=${VPAT_ID}`);
  await expect(page.getByText(/Confirmed by Priya N \(Accessibility lead\)/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Exports" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Create VPAT (PDF)" })).toBeVisible();
  await expect(page.getByRole("row", { name: "VPAT (PDF)" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Save changes" })).toHaveCount(0); // locked: no editing
  await expect(page.getByRole("button", { name: "Reopen to edit" })).toBeVisible();
  await audit(page, "signed vpat");
});

test("a member can read the VPAT but not edit, sign off or export it", async ({ page }) => {
  await mockApi(page, "STANDARD_USER");
  await page.goto(`/workspace/vpat?id=${VPAT_ID}`);
  await expect(page.getByText(/Only an administrator can edit, sign off or export this VPAT/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Save changes" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Sign off this VPAT" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Conformance level for/ })).toHaveCount(0);
  await expect(page.getByRole("row", { name: "WCAG 1.1.1 Non-text Content" })).toContainText("Does Not Support");
  await audit(page, "read-only vpat");
});

test("problems that block sign-off are listed", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await mockReportApi(page, { problems: ["WCAG 1.1.1 Non-text Content: automated tests found failures; explain why you are marking it 'Supports'."] });
  await page.goto(`/workspace/vpat?id=${VPAT_ID}`);
  await expect(page.getByText("Fix these before you can sign off:")).toBeVisible();
  await expect(page.getByText(/explain why you are marking it 'Supports'/)).toBeVisible();
});
