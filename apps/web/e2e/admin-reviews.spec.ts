import AxeBuilder from "@axe-core/playwright";
import { reviewAdmin } from "./admin-mocks";
import { expect, mockApi, test } from "./fixtures";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];
async function audit(page: import("@playwright/test").Page, what: string) {
  const r = await new AxeBuilder({ page }).withTags(TAGS).exclude("[data-live-announcer]").analyze();
  expect(r.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(" | ")})`), what).toEqual([]);
}
async function open(page: import("@playwright/test").Page) {
  reviewAdmin.calls.length = 0;
  await mockApi(page, "SUPER_ADMIN");
  await page.goto("/admin");
  await page.getByRole("tab", { name: "Reviews" }).click();
}

for (const scheme of ["light", "dark"] as const) {
  test(`admin reviews: queue health, turnaround, cost, in-progress files and reviewers (${scheme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await open(page);
    await expect(page.getByRole("heading", { level: 2, name: "! 1 review is overdue" })).toBeVisible(); // said in words, not only colour
    await expect(page.getByText("88%")).toBeVisible();
    await expect(page.getByText("₹342")).toBeVisible();
    await expect(page.getByText("₹18.5")).toBeVisible();
    await expect(page.getByText(/documents\.review/)).toBeVisible();
    await expect(page.getByText("asha@example.com has had it since")).toBeVisible();
    await expect(page.getByText("ravi@example.com").first()).toBeVisible();
    await expect(page.getByText(/ravi@example.com: Switched off/)).toBeVisible();
    await audit(page, "admin reviews");
  });
}

test("a file can be taken back, a reviewer switched on or off, by keyboard", async ({ page }) => {
  await open(page);
  const back = page.getByRole("button", { name: /Take back the file held by asha@example.com/ });
  await expect(back).toBeVisible();
  await back.press("Enter");
  await expect.poll(() => reviewAdmin.calls).toContain("release:rv7");
  await page.getByRole("button", { name: "Switch on ravi@example.com" }).press("Enter");
  await expect.poll(() => reviewAdmin.calls).toContain("active:u2:true");
  await page.getByRole("button", { name: "Switch off asha@example.com" }).press("Enter");
  await expect.poll(() => reviewAdmin.calls).toContain("active:u1:false");
});

test("a reviewer is created with a password that is checked, and an existing one can be given a new password", async ({ page }) => {
  await open(page);
  await page.getByLabel("Email address").fill("new@example.com");
  await page.getByLabel("First password").fill("short");
  await page.getByRole("button", { name: "Create reviewer" }).click();
  await expect(page.getByText("Use at least 12 characters.")).toBeVisible();
  await page.getByLabel("First password").fill("a-long-passphrase-123");
  await page.getByRole("button", { name: "Create reviewer" }).click();
  await expect.poll(() => reviewAdmin.calls.filter((c) => c.startsWith("create:"))).toEqual(["create:new@example.com", "create:new@example.com"]);
  await expect(page.getByText("Reviewer created. Pass the password on securely.")).toBeVisible();
  await page.getByRole("button", { name: "Set a new password for asha@example.com" }).click();
  const dialog = page.getByRole("dialog", { name: "Set a new password for asha@example.com" });
  await dialog.getByLabel("New password").fill("a-brand-new-passphrase-9");
  await dialog.getByRole("button", { name: "Change the password" }).click();
  await expect.poll(() => reviewAdmin.calls).toContain("password:u1");
});
