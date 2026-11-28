import AxeBuilder from "@axe-core/playwright";
import { AUDIT_DETAIL, docState, resetDocs } from "./document-mocks";
import { expect, mockApi, test } from "./fixtures";
import { REVIEW, resetReviews, reviewState } from "./review-mocks";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];
async function audit(page: import("@playwright/test").Page, what: string) {
  const r = await new AxeBuilder({ page }).withTags(TAGS).exclude("[data-live-announcer]").analyze();
  expect(r.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(" | ")})`), what).toEqual([]);
}
test.beforeEach(() => { resetDocs(); resetReviews(); });

// --- the customer asks -------------------------------------------------------------------------------------

for (const scheme of ["light", "dark"] as const) {
  test(`asking a person: the consent is written out, nothing is sent until it is agreed (${scheme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await mockApi(page, "COMPANY_ADMIN");
    await page.goto("/workspace/documents/audit?doc=d1&audit=a1");
    await expect(page.getByRole("heading", { level: 2, name: "Ask a person to check this" })).toBeVisible();
    await page.getByRole("button", { name: "Ask a person to check this" }).click();
    const dialog = page.getByRole("dialog", { name: "Ask a person to check this document" });
    await expect(dialog).toContainText("open this file");
    const send = dialog.getByRole("button", { name: "Send to a reviewer" });
    await expect(send).toBeDisabled(); // consent first
    await audit(page, "review dialog");
    await dialog.getByLabel(/Anything the reviewer should know/).fill("Please check the charts");
    await dialog.getByText("I agree to a person opening this file").click();
    await expect(send).toBeEnabled();
    await send.click();
    expect(reviewState.requests).toEqual([{ note: "Please check the charts", consent: true }]);
    await expect(page.getByText("Your request was sent.")).toBeVisible();
    await expect(page.getByText(/Waiting for a reviewer\. We aim to finish by/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Cancel the request" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Ask a person to check this" })).toHaveCount(0); // one at a time
  });
}

test("a request can be cancelled while it waits", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  reviewState.reviews = [REVIEW()];
  await page.goto("/workspace/documents/audit?doc=d1&audit=a1");
  await page.getByRole("button", { name: "Cancel the request" }).click();
  await expect.poll(() => reviewState.cancelled).toEqual(["rv1"]);
  await expect(page.getByText("Your request was cancelled and the review was not used.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Ask for another check" })).toBeVisible();
});

test("the customer is told what happened in words, and never who the reviewer was", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  reviewState.reviews = [REVIEW({ status: "COMPLETED", outcome_note: "Described the charts; please check the colours yourself.", result_document_id: "copy1", completed_at: "2026-11-29T09:00:00Z" })];
  await page.goto("/workspace/documents/audit?doc=d1&audit=a1");
  await expect(page.getByText(/A person has checked this document and made a fixed copy\. They say: Described the charts/)).toBeVisible();
  const dl = page.waitForRequest("**/api/documents/copy1/download");
  await page.getByRole("button", { name: "Download the fixed copy" }).click();
  await dl;
  reviewState.reviews = [REVIEW({ status: "DECLINED", outcome_note: "The scans are too blurred to read." })];
  await page.reload();
  await expect(page.getByText(/could not improve it\. The scans are too blurred/)).toBeVisible();
  reviewState.reviews = [REVIEW({ status: "IN_REVIEW" })];
  await page.reload();
  await expect(page.getByText("A reviewer is working on this document. You will get an email when they finish.")).toBeVisible();
  await audit(page, "review status");
});

test("a plan without reviews explains it and links to the plan", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  reviewState.requestError = { status: 409, json: { detail: "You have used 0 of 0 this month. Upgrade your plan for more.", code: "quota_exceeded" } };
  await page.goto("/workspace/documents/audit?doc=d1&audit=a1");
  await page.getByRole("button", { name: "Ask a person to check this" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByText("I agree to a person opening this file").click();
  await dialog.getByRole("button", { name: "Send to a reviewer" }).click();
  await expect(dialog.getByRole("alert")).toContainText("You have used 0 of 0 this month.");
  await expect(dialog.getByRole("link", { name: "See your plan" })).toHaveAttribute("href", "/org");
});

test("the documents list shows where a review stands", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  docState.docs = docState.docs.map((d) => (d.id === "d1" ? { ...d, latest_review: REVIEW({ status: "IN_REVIEW" }) } : d));
  await page.goto("/workspace/documents");
  await expect(page.getByText(/Human review: A reviewer is working on this document/)).toBeVisible();
});

test("when human review is switched off the panel is not offered", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await page.route("**/api/org/flags", (r) => r.fulfill({ json: { public_api: true, webhooks: true, vpat: true, crawl_scans: true, notification_center: true, documents: true, human_review: false } }));
  await page.goto("/workspace/documents/audit?doc=d1&audit=a1");
  await expect(page.getByRole("heading", { level: 2, name: "3 things to fix" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Ask a person to check this" })).toHaveCount(0);
});

// --- the reviewer's console ---------------------------------------------------------------------------------

for (const scheme of ["light", "dark"] as const) {
  test(`queue: counts and times only, overdue said in words, what is mine first (${scheme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await mockApi(page, "REVIEWER");
    await page.goto("/review");
    await expect(page.getByRole("heading", { level: 1, name: "Review queue" })).toBeVisible();
    await expect(page.getByText(/You see sizes and counts only/)).toBeVisible();
    const waiting = page.getByRole("table", { name: /Waiting for a reviewer/ });
    await expect(waiting.getByRole("row", { name: /40/ })).toContainText("Overdue");
    await expect(waiting.getByRole("row", { name: /3 scanned pages/ })).toContainText("not tagged");
    const text = await page.locator("main").innerText();
    expect(text).not.toMatch(/annual-report|Please check|@example/); // no names, notes or people
    await expect(page.getByRole("heading", { level: 2, name: "Files you are working on (1)" })).toBeVisible();
    await expect(page.getByRole("link", { name: /Open the file due/ })).toHaveAttribute("href", "/review/item?id=q9");
    await audit(page, "review queue");
  });
}

test("taking a file works by keyboard and opens it", async ({ page }) => {
  await mockApi(page, "REVIEWER");
  await page.goto("/review");
  const take = page.getByRole("button", { name: /Take this file due/ }).first();
  await expect(take).toBeVisible();
  await page.getByRole("button", { name: "Refresh the queue" }).focus();
  for (let i = 0; i < 10 && !(await take.evaluate((el) => el === document.activeElement)); i++) await page.keyboard.press("Tab");
  await expect(take).toBeFocused();
  await page.keyboard.press("Enter");
  await expect.poll(() => reviewState.claimed).toEqual(["q1"]);
  await expect(page).toHaveURL(/\/review\/item\?id=q1/);
});

test("a file someone else took says so plainly", async ({ page }) => {
  await mockApi(page, "REVIEWER");
  reviewState.claimError = { status: 409, json: { detail: "Someone else has taken this file, or the customer cancelled it.", code: "unavailable" } };
  await page.goto("/review");
  await page.getByRole("button", { name: /Take this file due/ }).first().click();
  await expect(page.getByText("Someone else has taken this file, or the customer cancelled it.")).toBeVisible();
});

for (const scheme of ["light", "dark"] as const) {
  test(`a claimed file: the file, what was found, the same editor the customer has, and how to finish (${scheme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await mockApi(page, "REVIEWER");
    await page.goto("/review/item?id=q9");
    await expect(page.getByRole("heading", { level: 2, name: "The file" })).toBeVisible();
    await expect(page.getByText("annual-report.pdf").first()).toBeVisible();
    await expect(page.getByText("Please look at the charts on page 5")).toBeVisible(); // the customer's note, shown only now
    await expect(page.getByRole("heading", { level: 2, name: "What the automated check found (3)" })).toBeVisible();
    await expect(page.getByText(/does not use any of the customer's document pages/)).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Alternative text for image 1, on page 2" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Deliver to the customer" })).toBeDisabled(); // nothing built yet
    await audit(page, "review workspace");
  });
}

test("fix, check the copy, deliver: only what changed is sent and delivery waits for a built copy", async ({ page }) => {
  await mockApi(page, "REVIEWER");
  await page.goto("/review/item?id=q9");
  await page.getByRole("textbox", { name: "Alternative text for image 1, on page 2" }).fill("A bar chart of revenue by quarter");
  await page.getByLabel("Title").fill("Annual report 2026");
  await page.getByRole("button", { name: "Build the fixed copy" }).click();
  await expect.poll(() => reviewState.builds).toBe(1);
  expect(reviewState.fixSaved.at(-1)).toEqual({ title: "Annual report 2026", alt: { "34-0": "A bar chart of revenue by quarter" }, heading_levels: {} });
  await expect(page.getByRole("heading", { level: 2, name: "Your fixed copy is ready" })).toBeVisible({ timeout: 15_000 });
  const dl = page.waitForRequest("**/api/review/q9/result");
  await page.getByRole("button", { name: "Download the fixed copy to check it" }).click();
  await dl;
  const deliver = page.getByRole("button", { name: "Deliver to the customer" });
  await expect(deliver).toBeEnabled();
  await page.getByLabel(/A message for the customer/).fill("Please check the colours yourself.");
  await page.getByLabel(/Minutes you spent/).fill("25");
  await deliver.click();
  await expect.poll(() => reviewState.submitted).toEqual([{ outcome: "deliver", message: "Please check the colours yourself.", minutes: 25 }]);
  await expect(page).toHaveURL(/\/review$/);
});

test("declining needs a reason and says what it will do", async ({ page }) => {
  await mockApi(page, "REVIEWER");
  await page.goto("/review/item?id=q9");
  await page.getByRole("radio", { name: "I could not improve this file" }).check();
  await expect(page.getByLabel(/Tell the customer why/)).toBeVisible();
  const submit = page.getByRole("button", { name: "Decline with this reason" });
  await expect(submit).toBeEnabled();
  reviewState.submitError = { status: 422, json: { detail: "Tell the customer why the file could not be improved (at least a sentence).", code: "reason_required" } };
  await submit.click();
  await expect(page.getByRole("alert").filter({ hasText: "Tell the customer why" })).toBeVisible();
  reviewState.submitError = null;
  await page.getByLabel(/Tell the customer why/).fill("The scans are too blurred to read; please send the original document.");
  await submit.click();
  await expect.poll(() => reviewState.submitted).toEqual([{ outcome: "decline", message: "The scans are too blurred to read; please send the original document.", minutes: null }]);
});

test("the original can be downloaded and the file put back in the queue", async ({ page }) => {
  await mockApi(page, "REVIEWER");
  await page.goto("/review/item?id=q9");
  const dl = page.waitForRequest("**/api/review/q9/original");
  await page.getByRole("button", { name: "Download the original" }).click();
  await dl;
  await page.getByRole("button", { name: "Put it back in the queue" }).click();
  await expect.poll(() => reviewState.released).toEqual(["q9"]);
  await expect(page).toHaveURL(/\/review$/);
});

test("a file that is not yours cannot be opened, and the page says why", async ({ page }) => {
  await mockApi(page, "REVIEWER");
  reviewState.detailError = { status: 403, json: { detail: "You are not working on this file.", code: "not_yours" } };
  await page.goto("/review/item?id=q1");
  await expect(page.getByText("You are not working on this file.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Back to the queue" }).first()).toBeVisible();
});

test("customers and organisation admins do not get the console, and reviewers do not get customer pages", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await page.goto("/review");
  await expect(page.getByRole("heading", { level: 1, name: "You do not have access" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Review queue" })).toHaveCount(0);
  const rev = await page.context().newPage();
  await mockApi(rev, "REVIEWER");
  await rev.goto("/workspace/documents");
  await expect(rev.getByText(/Platform staff do not have documents of their own/)).toBeVisible();
  await expect(rev.getByRole("link", { name: "Review queue" })).toBeVisible();
  await expect(rev.getByRole("link", { name: "Workspace" })).toHaveCount(0);
});

test("the audit results still show the fix link next to the review panel", async ({ page }) => {
  await mockApi(page, "COMPANY_ADMIN");
  await page.goto("/workspace/documents/audit?doc=d1&audit=a1");
  await expect(page.getByRole("link", { name: "Fix problems in this document" })).toBeVisible();
  expect(AUDIT_DETAIL.findings.length).toBe(3);
});
