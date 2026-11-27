import AxeBuilder from "@axe-core/playwright";
import { expect, mockApi, test } from "./fixtures";
import { mockWebhooks } from "./webhook-mocks";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];
async function audit(page: import("@playwright/test").Page, what: string) {
  const r = await new AxeBuilder({ page }).withTags(TAGS).exclude("[data-live-announcer]").analyze();
  expect(r.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(" | ")})`), what).toEqual([]);
}

for (const scheme of ["light", "dark"] as const) {
  test(`webhooks: list, add with one-time secret, deliveries and retry (${scheme})`, async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await page.emulateMedia({ colorScheme: scheme });
    await mockApi(page, "COMPANY_ADMIN");
    await mockWebhooks(page);
    await page.goto("/org/webhooks");
    await expect(page.getByRole("heading", { level: 1, name: "Webhooks" })).toBeVisible();
    await expect(page.getByRole("row", { name: /hooks\.example\.com/ })).toBeVisible();
    await expect(page.getByRole("row", { name: /old\.example\.com/ })).toContainText("Off: 20 deliveries in a row failed.");
    await audit(page, "webhooks: list");

    await page.getByLabel("Address").fill("https://receiver.example.com/a11y");
    await page.getByText(/A scan finished successfully/).click();
    await page.getByRole("button", { name: "Add webhook" }).click();
    const h = page.getByRole("heading", { level: 2, name: /Your signing secret: copy it now/ });
    await expect(h).toBeFocused();
    await expect(page.getByText(/whsec_SECRET/)).toBeVisible();
    await audit(page, "webhooks: one-time secret");
    await page.getByRole("button", { name: "Copy secret" }).click();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toMatch(/^whsec_/);
    await page.getByRole("button", { name: "I have stored it safely" }).click();
    await expect(h).toHaveCount(0);

    await page.getByRole("button", { name: /Deliveries for https:\/\/hooks\.example\.com/ }).click();
    const hist = page.getByRole("grid", { name: "Recent deliveries" });
    await expect(hist.getByRole("row", { name: /scan\.completed/ }).first()).toBeVisible();
    await expect(hist).toContainText("Gave up: HTTP 500");
    await audit(page, "webhooks: deliveries");
    await hist.getByRole("button", { name: /Retry/ }).click();
    await expect(page.getByText("Retrying now.")).toBeVisible();
  });
}

test("a refused address is explained next to the field", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await mockWebhooks(page);
  await page.goto("/org/webhooks");
  await page.getByLabel("Address").fill("http://insecure.example.com/hook");
  await page.getByText(/A scan finished successfully/).click();
  await page.getByRole("button", { name: "Add webhook" }).click();
  await expect(page.getByText("Webhook addresses must start with https://.").first()).toBeVisible();
});

test("an event must be chosen", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await mockWebhooks(page);
  await page.goto("/org/webhooks");
  await page.getByLabel("Address").fill("https://x.example.com/hook");
  await page.getByRole("button", { name: "Add webhook" }).click();
  await expect(page.getByText("Choose at least one event.").first()).toBeVisible();
});

test("test, turn off, rotate and delete each ask or confirm properly", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  const { calls } = await mockWebhooks(page);
  await page.goto("/org/webhooks");
  await page.getByRole("button", { name: /Send a test to https:\/\/hooks\.example\.com/ }).click();
  await expect(page.getByText(/A test event was queued/)).toBeVisible();
  await page.getByRole("button", { name: /Turn off https:\/\/hooks\.example\.com/ }).click();
  await expect(page.getByText("The webhook is now off.")).toBeVisible();

  await page.getByRole("button", { name: /Rotate secret for https:\/\/hooks\.example\.com/ }).click();
  const rotate = page.getByRole("dialog", { name: "Rotate the signing secret?" });
  await expect(rotate).toBeVisible();
  await rotate.getByRole("button", { name: "Rotate secret" }).click();
  await expect(page.getByRole("heading", { name: /Your new signing secret/ })).toBeFocused();

  await page.getByRole("button", { name: /Delete https:\/\/hooks\.example\.com/ }).click();
  const del = page.getByRole("dialog", { name: "Delete this webhook?" });
  await del.getByRole("button", { name: "Delete webhook" }).click();
  await expect(page.getByText("The webhook was deleted.")).toBeVisible();
  expect(calls).toEqual(expect.arrayContaining(["test", "off", "rotate", "delete"]));
});

test("a plan without API access, or a switched-off feature, says so", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await mockWebhooks(page, { entitled: false });
  await page.goto("/org/webhooks");
  await expect(page.getByText(/part of API access, which is not in your current plan/)).toBeVisible();
  await mockWebhooks(page, { entitled: false, switchedOff: true });
  await page.reload();
  await expect(page.getByText(/switched off for your account/)).toBeVisible();
});

test("members cannot manage webhooks", async ({ page }) => {
  await mockApi(page, "STANDARD_USER");
  await page.goto("/org/webhooks");
  await expect(page.getByRole("button", { name: "Add webhook" })).toHaveCount(0);
});
