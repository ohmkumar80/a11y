import AxeBuilder from "@axe-core/playwright";
import { expect, mockApi, test } from "./fixtures";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];
async function audit(page: import("@playwright/test").Page, what: string) {
  const r = await new AxeBuilder({ page }).withTags(TAGS).exclude("[data-live-announcer]").analyze();
  expect(r.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(" | ")})`), what).toEqual([]);
}

for (const scheme of ["light", "dark"] as const) {
  test(`a published legal page is readable by anyone, with real structure (${scheme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await mockApi(page, "ANON");
    await page.goto("/legal/terms");
    await expect(page.getByRole("heading", { level: 1, name: "Terms of service" })).toBeVisible();
    await expect(page.getByText("Version 2026-12, in force from")).toBeVisible();
    await expect(page.getByRole("heading", { level: 2, name: "1. Who we are" })).toBeVisible(); // the page title is the only h1
    await expect(page.getByRole("heading", { level: 3, name: "1.1 What you can do" })).toBeVisible();
    await expect(page.getByRole("listitem").filter({ hasText: "Keep your account secure." })).toBeVisible();
    await expect(page.getByRole("link", { name: "our site" })).toHaveAttribute("href", "https://example.com/about");
    await expect(page).toHaveTitle(/Terms of service/);
    await audit(page, "legal page");
  });
}

test("the text is never interpreted as HTML or as an unsafe link", async ({ page }) => {
  await mockApi(page, "ANON");
  await page.goto("/legal/terms");
  await expect(page.getByText(/<script>window\.__pwned = true<\/script>/)).toBeVisible(); // shown as text, not run
  expect(await page.evaluate(() => (window as unknown as { __pwned?: boolean }).__pwned)).toBeUndefined();
  await expect(page.getByRole("link", { name: /a bad link/ })).toHaveCount(0); // a javascript: address is not a link
});

test("the footer offers only the pages that are published", async ({ page }) => {
  await mockApi(page, "ANON");
  await page.goto("/help");
  const footer = page.getByRole("navigation", { name: "Footer" });
  await expect(footer.getByRole("link", { name: "Terms of service" })).toBeVisible();
  await expect(footer.getByRole("link", { name: "Privacy policy" })).toBeVisible();
  await expect(footer.getByRole("link", { name: "Cookie policy" })).toHaveCount(0);
  await footer.getByRole("link", { name: "Terms of service" }).click();
  await expect(page).toHaveURL(/\/legal\/terms/);
});

test("an unpublished page says so plainly", async ({ page }) => {
  await mockApi(page, "ANON");
  await page.goto("/legal/privacy");
  await expect(page.getByText(/This page has not been published yet/)).toBeVisible();
  await expect(page.getByRole("link", { name: "contact us" })).toBeVisible();
});
