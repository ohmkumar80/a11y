import AxeBuilder from "@axe-core/playwright";
import { AUDIT_DETAIL, docState, resetDocs } from "./document-mocks";
import { expect, mockApi, test } from "./fixtures";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];
async function audit(page: import("@playwright/test").Page, what: string) {
  const r = await new AxeBuilder({ page }).withTags(TAGS).exclude("[data-live-announcer]").analyze();
  expect(r.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(" | ")})`), what).toEqual([]);
}
const PDF = { name: "quarterly results.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.7 hello") };

test.beforeEach(() => resetDocs());

for (const scheme of ["light", "dark"] as const) {
  test(`documents: limits explained, files listed with plain statuses (${scheme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await mockApi(page, "COMPANY_ADMIN");
    await page.goto("/workspace/documents");
    await expect(page.getByRole("heading", { level: 1, name: "Documents" })).toBeVisible();
    await expect(page.getByText("PDF: up to 50 MB")).toBeVisible();
    await expect(page.getByText("Word: up to 25 MB")).toBeVisible();
    await expect(page.getByText(/deleted after 30 days/)).toBeVisible();
    const table = page.getByRole("table", { name: "Your documents" });
    await expect(table.getByRole("row", { name: /annual-report.pdf/ })).toContainText("Ready");
    await expect(table.getByRole("row", { name: /scan-copy.pdf/ })).toContainText("Not accepted");
    await expect(table.getByRole("row", { name: /scan-copy.pdf/ })).toContainText("password-protected"); // the reason, in words
    await expect(table.getByRole("row", { name: /board-pack.docx/ })).toContainText("Could not be checked");
    // a file that is not ready cannot be downloaded
    await expect(table.getByRole("row", { name: /scan-copy.pdf/ }).getByRole("button", { name: /Download/ })).toHaveCount(0);
    await audit(page, "documents");
  });
}

test("uploading sends the raw file, says what happens next, and the file moves to Ready", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await page.goto("/workspace/documents");
  const upload = page.getByRole("button", { name: "Upload", exact: true });
  await expect(upload).toBeDisabled(); // nothing chosen yet
  await page.getByLabel("File").setInputFiles(PDF);
  await expect(upload).toBeEnabled();
  await upload.click();
  await expect(page.getByText("“quarterly results.pdf” was uploaded. We are checking it now")).toBeVisible();
  expect(docState.uploads).toEqual([{ filename: "quarterly results.pdf", bytes: PDF.buffer.length }]);
  const row = page.getByRole("table", { name: "Your documents" }).getByRole("row", { name: /quarterly results.pdf/ });
  await expect(row).toContainText(/Waiting to be checked|Being checked/);
  await expect(row).toContainText("Ready", { timeout: 15_000 }); // the list refreshes by itself
  await expect(page.getByLabel("File")).toHaveValue(""); // the form is ready for the next one
});

test("a refused upload says why, next to the field, and keeps the file chosen", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  docState.uploadError = { status: 422, json: { detail: "That file has a .pdf name but is not a PDF.", code: "type_mismatch", field: "file" } };
  await page.goto("/workspace/documents");
  await page.getByLabel("File").setInputFiles(PDF);
  await page.getByRole("button", { name: "Upload", exact: true }).click();
  await expect(page.getByRole("alert").first()).toContainText("not a PDF");
  await expect(page.getByLabel("File")).toHaveAttribute("aria-invalid", "true");
  await audit(page, "documents: upload error");
});

test("download and delete work by keyboard alone, and delete asks first", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await page.goto("/workspace/documents");
  const dl = page.getByRole("button", { name: "Download annual-report.pdf" });
  await expect(dl).toBeVisible();
  // The real keyboard path: Tab from the file picker reaches the buttons in the table, Enter activates.
  await page.getByLabel("File").focus();
  for (let i = 0; i < 12 && !(await dl.evaluate((el) => el === document.activeElement)); i++) await page.keyboard.press("Tab");
  await expect(dl).toBeFocused();
  await page.keyboard.press("Enter");
  await expect.poll(() => docState.downloads).toEqual(["d1"]);
  await expect(page.getByText("“annual-report.pdf” was downloaded.")).toBeVisible();

  const del = page.getByRole("button", { name: "Delete scan-copy.pdf" });
  await del.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Delete “scan-copy.pdf”?" });
  await expect(dialog).toContainText("cannot be undone");
  expect(docState.deleted).toEqual([]); // nothing happens until confirmed
  await audit(page, "documents: delete dialog");
  await dialog.getByRole("button", { name: "Delete file" }).press("Enter");
  await expect.poll(() => docState.deleted).toEqual(["d2"]);
  await expect(page.getByText("“scan-copy.pdf” was deleted.")).toBeVisible();
  await expect(page.getByRole("table", { name: "Your documents" }).getByRole("row", { name: /scan-copy.pdf/ })).toHaveCount(0);
});

test("when uploads are off, the page says so instead of showing a broken form", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  docState.policy.enabled = false;
  await page.goto("/workspace/documents");
  await expect(page.getByText("Document uploads are switched off at the moment.")).toBeVisible();
  docState.policy.enabled = true;
});

test("when the feature flag is off, the workspace hides the link and the page explains", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await page.route("**/api/org/flags", (r) => r.fulfill({ json: { public_api: true, webhooks: true, vpat: true, crawl_scans: true, notification_center: true, documents: false } }));
  await page.goto("/workspace");
  await expect(page.getByRole("heading", { name: "Workspace" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Go to your documents" })).toHaveCount(0);
  await page.goto("/workspace/documents");
  await expect(page.getByText(/switched off for your account/)).toBeVisible();
});

test("the workspace links to documents", async ({ page }) => {
  await mockApi(page, "STANDARD_USER");
  await page.goto("/workspace");
  await page.getByRole("link", { name: "Go to your documents" }).click();
  await expect(page).toHaveURL(/\/workspace\/documents$/);
});

// --- PDF accessibility checks ------------------------------------------------------------------------------------


test("only a ready PDF can be checked; starting a check says so and the result appears by itself", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await page.goto("/workspace/documents");
  const table = page.getByRole("table", { name: "Your documents" });
  await expect(table.getByRole("row", { name: /scan-copy.pdf/ }).getByRole("button", { name: /Check accessibility/ })).toHaveCount(0); // not accepted
  await expect(table.getByRole("row", { name: /board-pack.docx/ }).getByRole("button", { name: /Check accessibility/ })).toHaveCount(0); // not ready and not a PDF
  const btn = table.getByRole("button", { name: "Check accessibility annual-report.pdf" });
  // The real keyboard path: Tab from the file picker, then Enter.
  await page.getByLabel("File").focus();
  for (let i = 0; i < 12 && !(await btn.evaluate((el) => el === document.activeElement)); i++) await page.keyboard.press("Tab");
  await expect(btn).toBeFocused();
  await page.keyboard.press("Enter");
  await expect.poll(() => docState.auditsStarted).toEqual(["d1"]);
  await expect(page.getByText("Checking “annual-report.pdf” now.")).toBeVisible();
  const row = table.getByRole("row", { name: /annual-report.pdf/ });
  await expect(row).toContainText("Accessibility check: 3 problems found", { timeout: 15_000 });
  await expect(row.getByRole("link", { name: "View results for annual-report.pdf" })).toHaveAttribute("href", /audit=a1/);
  await expect(row.getByRole("button", { name: /Check again/ })).toBeVisible();
});

test("a page quota that is used up explains it and links to the plan", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  docState.auditError = { status: 409, json: { detail: "You have used 50 of 50 this month. Upgrade your plan for more.", code: "quota_exceeded" } };
  await page.goto("/workspace/documents");
  await page.getByRole("button", { name: "Check accessibility annual-report.pdf" }).click();
  await expect(page.getByText("You have used 50 of 50 this month.")).toBeVisible();
  await expect(page.getByRole("link", { name: "See your plan" })).toHaveAttribute("href", "/org");
});

for (const scheme of ["light", "dark"] as const) {
  test(`results: honest summary, worst problems first, each with how to fix it (${scheme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await mockApi(page, "COMPANY_ADMIN");
    await page.goto("/workspace/documents/audit?doc=d1&audit=a1");
    await expect(page.getByRole("heading", { level: 1, name: "Document check results" })).toBeVisible();
    await expect(page.getByText("annual-report.pdf")).toBeVisible();
    await expect(page.getByRole("heading", { level: 2, name: "3 things to fix" })).toBeVisible();
    await expect(page.getByText(/Not a guarantee\./)).toBeVisible();
    await expect(page.getByText(/1 of these need a person/)).toBeVisible();
    const heads = await page.getByRole("heading", { level: 2 }).allTextContents();
    expect(heads.filter((h) => /^(Critical|Serious|Moderate)/.test(h))).toEqual(["Critical (1)", "Serious (1)", "Moderate (1)"]);
    const scanned = page.getByRole("article").filter({ hasText: "pictures of text" });
    await expect(scanned).toContainText("Critical");
    await expect(scanned).toContainText("Pages 3, 4");
    await expect(scanned).toContainText("How to fix it: Run text recognition (OCR)");
    const alt = page.getByRole("article").filter({ hasText: "no alternative text" });
    await expect(alt).toContainText("Needs a person");
    await expect(alt).toContainText("Relates to WCAG 1.1.1");
    await alt.getByText("Technical details").click();
    await expect(alt.getByText("Figure tag has no alternative text", { exact: false })).toBeVisible();
    await expect(page.getByText("Pages that are only pictures")).toBeVisible();
    await audit(page, "document audit results");
  });
}

test("a check that found nothing still says it is not a guarantee", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  docState.auditDetail = { ...AUDIT_DETAIL, findings: [], summary: { ...AUDIT_DETAIL.summary, verdict: "no_automated_problems", findings: 0, needs_a_person: 0, by_severity: { critical: 0, serious: 0, moderate: 0, minor: 0 } } };
  await page.goto("/workspace/documents/audit?doc=d1&audit=a1");
  await expect(page.getByRole("heading", { level: 2, name: "The automated checks found no problems" })).toBeVisible();
  await expect(page.getByText(/Not a guarantee\./)).toBeVisible();
  await expect(page.getByRole("article")).toHaveCount(0);
});

test("a failed check explains whose fault it was", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  docState.auditDetail = { ...AUDIT_DETAIL, status: "FAILED", summary: {}, findings: [], error_code: "system_fault", error_detail: "We could not finish checking this file because of a problem on our side. Your pages were not used. Please try again later." };
  await page.goto("/workspace/documents/audit?doc=d1&audit=a1");
  await expect(page.getByText(/problem on our side\. Your pages were not used/)).toBeVisible();
  await audit(page, "document audit failed");
});

test("the results page asks for a document and a check when opened without them", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await page.goto("/workspace/documents/audit");
  await expect(page.getByText(/needs a document and a check/)).toBeVisible();
});
