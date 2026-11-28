import AxeBuilder from "@axe-core/playwright";
import allowlist from "./axe-allowlist.json" with { type: "json" };
import { expect, mockApi, test } from "./fixtures";
import { ROUTES } from "./routes";


const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];

test("allow-list entries are complete and unexpired", () => {
  for (const e of allowlist.entries as Array<{ rule: string; issue: string; expires: string }>) {
    expect(e.issue, `allow-list entry for ${e.rule} needs an issue link`).toMatch(/^https?:\/\//);
    expect(new Date(e.expires).getTime(), `allow-list entry for ${e.rule} expired on ${e.expires}`).toBeGreaterThan(Date.now());
  }
});

for (const scheme of ["light", "dark"] as const) {
  for (const { path, roles } of ROUTES) {
    for (const role of roles) {
      test(`axe: ${path} as ${role} (${scheme})`, async ({ page }) => {
        await page.emulateMedia({ colorScheme: scheme });
        await mockApi(page, role);
        await page.goto(path);
        // Wait for client-side auth to settle so we audit the real page, not the loading state.
        await expect(page.locator("main h1")).not.toHaveText("Loading");
        await page.waitForLoadState("networkidle");

        const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
        const allowed = new Set((allowlist.entries as Array<{ rule: string; route: string }>).filter((e) => path.startsWith(e.route)).map((e) => e.rule));
        const violations = results.violations.filter((v) => !allowed.has(v.id));
        expect(
          violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(" | ")})`),
        ).toEqual([]);
      });
    }
  }
}

test("axe: forced-colors mode on key routes", async ({ page }) => {
  await page.emulateMedia({ forcedColors: "active" });
  await mockApi(page, "COMPANY_ADMIN");
  for (const path of ["/login", "/org"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
    expect(results.violations.map((v) => v.id), path).toEqual([]);
  }
});
