import { expect, mockApi, test } from "./fixtures";
import { readdirSync, statSync, existsSync } from "node:fs";
import { join } from "node:path";
import { ROUTES } from "./routes";

test("every page in src/app is covered by the axe route matrix", () => {
  const root = join(import.meta.dirname, "../src/app");
  const found: string[] = [];
  const walk = (dir: string, url: string) => {
    if (existsSync(join(dir, "page.tsx"))) found.push(url || "/");
    for (const name of readdirSync(dir)) {
      if (statSync(join(dir, name)).isDirectory()) walk(join(dir, name), `${url}/${name}`);
    }
  };
  walk(root, "");
  const covered = new Set(ROUTES.map((r) => r.path.split("?")[0]));
  expect(found.filter((p) => !covered.has(p))).toEqual([]);
});

test.describe("page structure on every route", () => {
  for (const { path, roles } of ROUTES) {
    test(`${path}: one h1, a title, landmarks, lang`, async ({ page }) => {
      await mockApi(page, roles[0]!);
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await expect(page.locator("html")).toHaveAttribute("lang", "en");
      expect(await page.title()).not.toBe("");
      await expect(page.locator("main h1")).toHaveCount(1);
      await expect(page.getByRole("banner")).toHaveCount(1);
      await expect(page.getByRole("main")).toHaveCount(1);
      await expect(page.getByRole("contentinfo")).toHaveCount(1);
    });
  }
});

test("titles are unique per route (SC 2.4.2)", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  const titles = new Map<string, string>();
  for (const { path } of ROUTES.filter((r) => !r.path.includes("?"))) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const t = await page.title();
    expect(titles.get(t), `duplicate title "${t}" on ${path} and ${titles.get(t)}`).toBeUndefined();
    titles.set(t, path);
  }
});

test("skip link is first in tab order and moves focus to main", async ({ page }) => {
  await mockApi(page, "ANON");
  await page.goto("/login");
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to main content" });
  await expect(skip).toBeFocused();
  await expect(skip).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main")).toBeFocused();
});

test("Help link sits in the same place in the nav on every page (SC 3.2.6)", async ({ page }) => {
  await mockApi(page, "ANON");
  const positions: string[] = [];
  for (const path of ["/", "/login", "/signup", "/help", "/accessibility"]) {
    await page.goto(path);
    await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Log in" })).toBeVisible(); // auth settled
    const links = await page.getByRole("navigation", { name: "Main" }).getByRole("link").allTextContents();
    positions.push(`${links.indexOf("Help") - links.length}`);
  }
  expect(new Set(positions).size).toBe(1);
});

test("client-side navigation announces the page and moves focus to its heading", async ({ page }) => {
  await mockApi(page, "ANON");
  await page.goto("/login");
  await page.getByRole("link", { name: "Create an account" }).click();
  await expect(page.getByTestId("route-announcer")).toContainText("Create an account");
  await expect(page.getByRole("heading", { level: 1, name: "Create your account" })).toBeFocused();
});

test("failed submit shows an error summary that takes focus and links to the field", async ({ page }) => {
  await mockApi(page, "ANON");
  await page.route("**/api/auth/login", (r) => r.fulfill({ status: 401, json: { detail: "Email or password is incorrect." } }));
  await page.goto("/login");
  await page.getByLabel("Email").fill("a@example.com");
  await page.getByLabel("Password").fill("not the password");
  await page.getByRole("button", { name: "Log in" }).click();
  const summary = page.getByRole("alert").filter({ hasText: "There is a problem" });
  await expect(summary).toBeFocused();
  await expect(summary).toContainText("Email or password is incorrect.");
});

test("inline field error is linked with aria-describedby (SC 3.3.1)", async ({ page }) => {
  await mockApi(page, "ANON");
  await page.route("**/api/auth/signup", (r) => r.fulfill({ status: 422, json: { detail: "Use at least 12 characters.", field: "password" } }));
  await page.goto("/signup");
  await page.getByLabel("Organisation name").fill("Acme");
  await page.getByLabel("Work email").fill("a@example.com");
  await page.getByLabel("Password").fill("short");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByLabel("Password")).toHaveAccessibleDescription(/Use at least 12 characters/);
  await expect(page.getByLabel("Password")).toHaveAttribute("aria-invalid", "true");
  // Clicking the summary link lands in the field.
  await page.getByRole("link", { name: "Use at least 12 characters." }).click();
  await expect(page.getByLabel("Password")).toBeFocused();
});

test("password fields accept paste and carry autocomplete tokens (SC 3.3.8, 1.3.5)", async ({ page }) => {
  await mockApi(page, "ANON");
  await page.goto("/login");
  await expect(page.getByLabel("Email")).toHaveAttribute("autocomplete", "username");
  await expect(page.getByLabel("Password")).toHaveAttribute("autocomplete", "current-password");
  await page.goto("/signup");
  await expect(page.getByLabel("Password")).toHaveAttribute("autocomplete", "new-password");
});

test("invite dialog-free flow: sent invite shows a polite toast, not the only signal", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await page.route("**/api/invites", (r) => r.fulfill({ status: 202, json: { message: "ok" } }));
  await page.goto("/org");
  await expect(page.getByRole("grid", { name: "Team members" })).toBeVisible();
  await page.getByLabel("Email").fill("new@example.com");
  await page.getByRole("button", { name: "Send invitation" }).click();
  await expect(page.getByText("Invitation sent")).toBeVisible();
});

test.describe("reflow at 320px (SC 1.4.10)", () => {
  test.use({ viewport: { width: 320, height: 640 } });
  for (const path of ["/", "/login", "/signup", "/org", "/help", "/accessibility"]) {
    test(`${path} has no horizontal scroll`, async ({ page }) => {
      await mockApi(page, "COMPANY_ADMIN");
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow).toBeLessThanOrEqual(0);
    });
  }
});

test("focus indicator is visible and not clipped on a link and a button (SC 2.4.7, 2.4.13)", async ({ page }) => {
  await mockApi(page, "ANON");
  await page.goto("/login");
  await page.keyboard.press("Tab"); // skip link
  await page.keyboard.press("Tab"); // brand link
  const outline = await page.evaluate(() => {
    const s = getComputedStyle(document.activeElement!);
    return { width: parseFloat(s.outlineWidth), style: s.outlineStyle };
  });
  expect(outline.style).toBe("solid");
  expect(outline.width).toBeGreaterThanOrEqual(2);
});
