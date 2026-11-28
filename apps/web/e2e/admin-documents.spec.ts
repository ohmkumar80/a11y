import AxeBuilder from "@axe-core/playwright";
import { docsState } from "./admin-mocks";
import { expect, mockApi, test } from "./fixtures";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];
async function audit(page: import("@playwright/test").Page, what: string) {
  const r = await new AxeBuilder({ page }).withTags(TAGS).exclude("[data-live-announcer]").analyze();
  expect(r.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(" | ")})`), what).toEqual([]);
}
async function open(page: import("@playwright/test").Page) {
  await mockApi(page, "SUPER_ADMIN");
  await page.goto("/admin");
  await page.getByRole("tab", { name: "Documents" }).click();
}

for (const scheme of ["light", "dark"] as const) {
  test(`admin documents: health, pipeline, refusal reasons and failed files (${scheme})`, async ({ page }) => {
    docsState.healthy = true;
    await page.emulateMedia({ colorScheme: scheme });
    await open(page);
    await expect(page.getByRole("heading", { level: 2, name: /Uploads are being checked/ })).toBeVisible();
    await expect(page.getByText("Passed all checks")).toBeVisible();
    const why = page.getByRole("grid", { name: "Reasons files were refused" });
    await expect(why.getByRole("row", { name: /Password-protected/ })).toContainText("2");
    await expect(why.getByRole("row", { name: /Virus found/ })).toContainText("1");
    await expect(page.getByRole("list", { name: "Files we could not check" }).getByRole("listitem")).toContainText("virus scanner unavailable");
    await expect(page.getByText(/documents.uploads, documents.safety and documents.retention/)).toBeVisible();
    const regions = page.getByRole("region", { name: "Where files are stored" });
    await expect(regions).toContainText("default: 10 files, storage working");
    await expect(regions).toContainText("eu: 3 files, storage not reachable"); // said in words
    await expect(regions).toContainText("This region is no longer configured"); // never hidden
    await audit(page, "admin documents");
  });
}

test("a down scanner is stated in words, not only colour", async ({ page }) => {
  docsState.healthy = false;
  await open(page);
  await expect(page.getByRole("heading", { level: 2, name: /Uploads are being held back/ })).toBeVisible();
  await expect(page.getByText(/Virus scanner: not reachable/)).toBeVisible();
  await expect(page.getByText(/nothing is let through unchecked/)).toBeVisible();
  docsState.healthy = true;
});

test("a failed file can be tried again, and expired files erased now, by keyboard", async ({ page }) => {
  docsState.healthy = true;
  docsState.rescans.length = 0;
  docsState.purges = 0;
  await open(page);
  const retry = page.getByRole("button", { name: /Try again for the PDF from Acme Ltd/ });
  await expect(retry).toBeVisible();
  // The real keyboard path: Tab from the sweep button reaches the retry button, and Enter activates it.
  await page.getByRole("button", { name: "Erase expired files now" }).focus();
  for (let i = 0; i < 12 && !(await retry.evaluate((el) => el === document.activeElement)); i++) await page.keyboard.press("Tab");
  await expect(retry).toBeFocused();
  await page.keyboard.press("Enter");
  await expect.poll(() => docsState.rescans).toEqual(["doc-f1"]);
  await expect(page.getByText("The file will be checked again")).toBeVisible();
  await page.getByRole("button", { name: "Erase expired files now" }).click();
  await expect.poll(() => docsState.purges).toBe(1);
  await expect(page.getByText("4 expired files erased")).toBeVisible();
});
