import AxeBuilder from "@axe-core/playwright";
import { policyState, resetPolicy } from "./data-policy-mocks";
import { expect, mockApi, test } from "./fixtures";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];
async function audit(page: import("@playwright/test").Page, what: string) {
  const r = await new AxeBuilder({ page }).withTags(TAGS).exclude("[data-live-announcer]").analyze();
  expect(r.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(" | ")})`), what).toEqual([]);
}
test.beforeEach(() => resetPolicy());

for (const scheme of ["light", "dark"] as const) {
  test(`data policy: what is in force, and one clear control per decision (${scheme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await mockApi(page, "COMPANY_ADMIN");
    await page.goto("/org/data-policy");
    await expect(page.getByRole("heading", { level: 1, name: "Data policy" })).toBeVisible();
    const now = page.getByRole("region", { name: "What is in force now" });
    await expect(now).toContainText("30 days (your plan allows up to 30)");
    await expect(now).toContainText("Default region");
    await expect(now).toContainText("AI models may process your documents");
    await expect(page.getByLabel("Keep files for (days)")).toBeEnabled();
    await expect(page.getByRole("button", { name: /Region for new files/ })).toBeVisible();
    await expect(page.getByText("Files already stored stay where they are: 3 in default, 1 in eu.")).toBeVisible();
    await audit(page, "data policy");
  });
}

test("a control the plan does not include is shown, switched off, with the reason in words", async ({ page }) => {
  resetPolicy({ can_choose_region: false, can_enable_ai: false, can_set_retention: false, can_block_human_review: false });
  await mockApi(page, "COMPANY_ADMIN");
  await page.goto("/org/data-policy");
  await expect(page.getByLabel("Keep files for (days)")).toBeDisabled();
  await expect(page.getByText(/Choosing a shorter time is not part of your plan/)).toBeVisible();
  await expect(page.getByText(/Choosing a region is not part of your plan/)).toBeVisible();
  await expect(page.getByRole("checkbox", { name: "Allow AI models to process my documents" })).toBeDisabled();
  await expect(page.getByText("Using AI on documents is not part of your plan.")).toBeVisible();
  await expect(page.getByRole("checkbox", { name: /Allow people on the a11y review team/ })).toBeDisabled();
  await audit(page, "data policy, limited plan");
});

test("saving sends only the organisation's choices and says what changed", async ({ page }) => {
  resetPolicy({ can_enable_ai: true });
  policyState.shortened = 2;
  await mockApi(page, "COMPANY_ADMIN");
  await page.goto("/org/data-policy");
  await page.getByLabel("Keep files for (days)").fill("7");
  await page.getByRole("button", { name: /Region for new files/ }).click();
  await page.getByRole("option", { name: "European Union (Frankfurt)" }).click();
  await page.getByText("Allow AI models to process my documents").click();
  await page.getByText("EU", { exact: true }).click();
  await page.getByRole("button", { name: "Save the policy" }).click();
  await expect(page.getByText("Saved. 2 stored files now expire sooner. The policy applies from now on.")).toBeVisible();
  expect(policyState.saved.at(-1)).toEqual({ retention_days: 7, storage_region: "eu", allow_human_review: true, ai_on_documents: true, ai_require_zero_retention: true, ai_regions: ["eu"] });
  await expect(page.getByRole("region", { name: "What is in force now" })).toContainText("7 days");
});

test("a refused choice is explained next to the field", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  policyState.saveError = { status: 422, json: { detail: "Your plan keeps files for at most 30 days. Choose a shorter time.", field: "retention_days" } };
  await page.goto("/org/data-policy");
  await page.getByLabel("Keep files for (days)").fill("90");
  await page.getByRole("button", { name: "Save the policy" }).click();
  await expect(page.getByText("Your plan keeps files for at most 30 days. Choose a shorter time.")).toBeVisible();
  await expect(page.getByLabel("Keep files for (days)")).toHaveAttribute("aria-invalid", "true");
});

test("deleting every document asks first, then says how many went", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await page.goto("/org/data-policy");
  await page.getByRole("button", { name: "Delete all my documents" }).press("Enter");
  const dialog = page.getByRole("dialog", { name: "Delete all your documents?" });
  await expect(dialog).toContainText("4 stored documents will be erased now");
  expect(policyState.deleteCalls).toEqual([]); // nothing happens until confirmed
  await audit(page, "data policy delete dialog");
  await dialog.getByRole("button", { name: "Delete every document" }).press("Enter");
  await expect.poll(() => policyState.deleteCalls).toEqual([{ confirm: true }]);
  await expect(page.getByText("4 documents were deleted.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Delete all my documents" })).toBeDisabled();
});

test("members cannot open it, and the organisation page and upload page link to it", async ({ page }) => {
  await mockApi(page, "STANDARD_USER");
  await page.goto("/org/data-policy");
  await expect(page.getByRole("heading", { level: 1, name: "You do not have access" })).toBeVisible();
  const admin = await page.context().newPage();
  await mockApi(admin, "COMPANY_ADMIN");
  await admin.goto("/org");
  await admin.getByRole("link", { name: "Manage your data policy" }).click();
  await expect(admin).toHaveURL(/\/org\/data-policy$/);
  await admin.goto("/workspace/documents");
  await expect(admin.getByRole("link", { name: "Your data policy" })).toHaveAttribute("href", "/org/data-policy");
});
