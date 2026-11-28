import AxeBuilder from "@axe-core/playwright";
import { FIX_STATE, docState, resetDocs } from "./document-mocks";
import { expect, mockApi, test } from "./fixtures";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];
async function audit(page: import("@playwright/test").Page, what: string) {
  const r = await new AxeBuilder({ page }).withTags(TAGS).exclude("[data-live-announcer]").analyze();
  expect(r.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(" | ")})`), what).toEqual([]);
}
test.beforeEach(() => resetDocs());

for (const scheme of ["light", "dark"] as const) {
  test(`fix editor: properties, one field per image, a level per heading, all labelled (${scheme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await mockApi(page, "COMPANY_ADMIN");
    await page.goto("/workspace/documents/fix?doc=d1");
    await expect(page.getByRole("heading", { level: 1, name: "Fix a document" })).toBeVisible();
    await expect(page.getByText(/The original is never changed/)).toBeVisible();
    await expect(page.getByText(/uses 12 of your document pages/)).toBeVisible();
    await expect(page.getByRole("group", { name: "Document properties" })).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Alternative text for image 1, on page 2" })).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Alternative text for image 2, on page 5" })).toBeVisible();
    await expect(page.getByText("Now: “Old description of the chart”.")).toBeVisible();
    await expect(page.getByRole("button", { name: /Level of the heading “Our results”, page 1/ })).toContainText("Level 3");
    await expect(page.getByText(/Page previews are not available yet/)).toBeVisible();
    await audit(page, "fix editor");
  });
}

test("only what the person changed is sent, and building shows progress, then an honest before and after", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await page.goto("/workspace/documents/fix?doc=d1");
  await page.getByLabel("Title").fill("Annual report 2026");
  await page.getByRole("button", { name: /Language/ }).click();
  await page.getByRole("option", { name: "English (UK)" }).click();
  await page.getByRole("textbox", { name: "Alternative text for image 1, on page 2" }).fill("A bar chart of revenue by quarter");
  await page.getByRole("button", { name: /Level of the heading “Our results”/ }).click();
  await page.getByRole("option", { name: "Level 2" }).click();
  await page.getByRole("button", { name: "Save for later" }).click();
  await expect(page.getByText("Your changes are saved. Nothing has been changed in the file yet.")).toBeVisible();
  expect(docState.fixSaved.at(-1)).toEqual({ title: "Annual report 2026", language: "en-GB", alt: { "34-0": "A bar chart of revenue by quarter" }, heading_levels: { "31-0": 2 } });

  await page.getByRole("button", { name: "Build the fixed copy" }).click();
  await expect.poll(() => docState.fixBuilds).toBe(1);
  await expect(page.getByRole("heading", { level: 2, name: "Your fixed copy is ready" })).toBeVisible({ timeout: 15_000 });
  const result = page.getByRole("region", { name: "Your fixed copy is ready" });
  await expect(result).toContainText("Before: 4 problems (Critical: 0, Serious: 2, Moderate: 1, Minor: 1)");
  await expect(result).toContainText("After: 1 problem (Critical: 0, Serious: 0, Moderate: 0, Minor: 1)");
  await expect(result.getByRole("listitem").filter({ hasText: "Images have no alternative text" })).toBeVisible();
  await expect(result.getByRole("listitem").filter({ hasText: "Minor: The PDF does not state" })).toBeVisible(); // what is still to do, in words
  await expect(result).toContainText("Not a guarantee.");
  const dl = page.waitForRequest("**/api/documents/copy1/download");
  await result.getByRole("button", { name: "Download the fixed copy" }).click();
  await dl;
  await audit(page, "fix result");
});

test("an unchanged heading level is not sent, and a blank image description means 'keep'", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await page.goto("/workspace/documents/fix?doc=d1");
  await page.getByLabel("Title").fill("Only a title");
  await page.getByRole("button", { name: "Save for later" }).click();
  await expect(page.getByText("Your changes are saved.")).toBeVisible();
  expect(docState.fixSaved.at(-1)).toEqual({ title: "Only a title", alt: {}, heading_levels: {} });
});

test("a used-up allowance explains it and links to the plan; the draft is kept", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  docState.fixBuildError = { status: 409, json: { detail: "You have used 50 of 50 this month. Upgrade your plan for more.", code: "quota_exceeded" } };
  await page.goto("/workspace/documents/fix?doc=d1");
  await page.getByLabel("Title").fill("A title");
  await page.getByRole("button", { name: "Build the fixed copy" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "You have used 50 of 50" })).toBeVisible();
  await expect(page.getByRole("link", { name: "See your plan" })).toHaveAttribute("href", "/org");
  expect(docState.fixSaved.length).toBeGreaterThan(0); // saved before the build was attempted
});

test("a failed build says whose fault it was and that nothing was charged", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  docState.fixState = { ...FIX_STATE, fix: { id: "fx1", status: "FAILED", plan: {}, pages: 12, result: {}, result_document_id: null, error_code: "system_fault", error_detail: "We could not finish this because of a problem on our side. Your pages were not used. Please try again later." } };
  await page.goto("/workspace/documents/fix?doc=d1");
  await expect(page.getByRole("heading", { level: 2, name: "The fixed copy could not be made" })).toBeVisible();
  await expect(page.getByText(/Your pages were not used/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Build the fixed copy" })).toBeEnabled(); // can try again
  await audit(page, "fix failed");
});

test("a file with no tags can only have its title and language set, and says why", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  docState.fixState = { ...FIX_STATE, structure: { ...FIX_STATE.structure, has_structure: false, figures: [], headings: [] } };
  await page.goto("/workspace/documents/fix?doc=d1");
  await expect(page.getByText(/This file has no tags, so image descriptions and heading levels cannot be changed here/)).toBeVisible();
  await expect(page.getByRole("group", { name: /Images/ })).toHaveCount(0);
  await expect(page.getByLabel("Title")).toBeVisible();
  await audit(page, "fix untagged");
});

test("a file that has not been checked yet is sent back to check it first", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  docState.fixLoadError = { status: 409, json: { detail: "Check this document's accessibility first, then you can fix what was found.", code: "needs_audit" } };
  await page.goto("/workspace/documents/fix?doc=d1");
  await expect(page.getByText(/Check this document's accessibility first/)).toBeVisible();
  await expect(page.getByRole("link", { name: "Go to your documents" })).toBeVisible();
});

test("the results page links to the fixer, and the list marks a fixed copy", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await page.goto("/workspace/documents/audit?doc=d1&audit=a1");
  await page.getByRole("link", { name: "Fix problems in this document" }).click();
  await expect(page).toHaveURL(/\/workspace\/documents\/fix\?doc=d1/);
  docState.docs = docState.docs.map((d) => (d.id === "d1" ? { ...d, derived_from: "d9" } : d));
  await page.goto("/workspace/documents");
  await expect(page.getByText("A fixed copy made from another of your documents")).toBeVisible();
});

test("the editor works by keyboard from the first field to the build button", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await page.goto("/workspace/documents/fix?doc=d1");
  await page.getByLabel("Title").focus();
  await page.keyboard.type("Keyboard title");
  const build = page.getByRole("button", { name: "Build the fixed copy" });
  for (let i = 0; i < 20 && !(await build.evaluate((el) => el === document.activeElement)); i++) await page.keyboard.press("Tab");
  await expect(build).toBeFocused();
  await page.keyboard.press("Enter");
  await expect.poll(() => docState.fixBuilds).toBe(1);
  expect((docState.fixSaved.at(-1) as { title: string }).title).toBe("Keyboard title");
});
