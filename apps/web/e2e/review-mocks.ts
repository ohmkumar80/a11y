import type { Page } from "@playwright/test";
import { AUDIT_DETAIL, FIX_READY, FIX_STATE } from "./document-mocks";

const iso = (hours: number) => new Date(Date.now() + hours * 3_600_000).toISOString();

const REVIEW = (over: Record<string, unknown> = {}) => ({
  id: "rv1", document_id: "d1", status: "REQUESTED", requested_at: "2026-11-28T09:00:00Z", due_at: "2026-11-30T09:00:00Z", completed_at: null,
  note: "Please check the charts", outcome_note: null, result_document_id: null, pages: 12, ...over,
});

export const reviewState = {
  consentText: "I ask a person on the a11y review team to open this file, see its contents, and try to fix its accessibility problems.",
  reviews: [] as Record<string, unknown>[],
  requests: [] as Record<string, unknown>[],
  cancelled: [] as string[],
  requestError: null as null | { status: number; json: Record<string, unknown> },
  queue: [] as Record<string, unknown>[],
  claimed: [] as string[],
  released: [] as string[],
  claimError: null as null | { status: number; json: Record<string, unknown> },
  detailError: null as null | { status: number; json: Record<string, unknown> },
  fix: null as null | Record<string, unknown>,
  fixSaved: [] as Record<string, unknown>[],
  builds: 0,
  submitted: [] as Record<string, unknown>[],
  submitError: null as null | { status: number; json: Record<string, unknown> },
  downloads: [] as string[],
};

const item = (id: string, over: Record<string, unknown> = {}) => ({
  id, status: "REQUESTED", mine: false, requested_at: iso(-20), due_at: iso(28), overdue: false, pages: 12, claimed_at: null,
  snapshot: { findings: 4, by_severity: { critical: 1, serious: 2, moderate: 1, minor: 0 }, tagged: true, figures: 2, headings: 5, image_only_pages: 0 }, ...over,
});

export function resetReviews() {
  reviewState.reviews = [];
  reviewState.requests = [];
  reviewState.cancelled = [];
  reviewState.requestError = null;
  reviewState.queue = [item("q1", { due_at: iso(-3), overdue: true, pages: 40 }), item("q2", { pages: 3, snapshot: { findings: 1, by_severity: { critical: 0, serious: 1, moderate: 0, minor: 0 }, tagged: false, figures: 0, headings: 0, image_only_pages: 3 } }), item("q9", { status: "IN_REVIEW", mine: true, claimed_at: iso(-1), due_at: iso(10) })];
  reviewState.claimed = [];
  reviewState.released = [];
  reviewState.claimError = null;
  reviewState.detailError = null;
  reviewState.fix = null;
  reviewState.fixSaved = [];
  reviewState.builds = 0;
  reviewState.submitted = [];
  reviewState.submitError = null;
  reviewState.downloads = [];
}
resetReviews();
export { REVIEW };

export async function mockReviewApi(page: Page) {
  // --- the customer's side
  await page.route(/\/api\/documents\/[^/?]+\/reviews\/[^/?]+$/, (r) => {
    reviewState.cancelled.push(r.request().url().split("/").pop() ?? "");
    reviewState.reviews = reviewState.reviews.map((x) => ({ ...x, status: "CANCELLED" }));
    return r.fulfill({ status: 204, body: "" });
  });
  await page.route(/\/api\/documents\/[^/?]+\/reviews$/, (r) => {
    if (r.request().method() === "POST") {
      if (reviewState.requestError) return r.fulfill({ status: reviewState.requestError.status, json: reviewState.requestError.json });
      const body = r.request().postDataJSON() as Record<string, unknown>;
      reviewState.requests.push(body);
      reviewState.reviews = [REVIEW({ note: body.note ?? null })];
      return r.fulfill({ status: 202, json: reviewState.reviews[0] });
    }
    return r.fulfill({ json: { consent: { version: "2026-11-28", text: reviewState.consentText }, reviews: reviewState.reviews } });
  });

  // --- the reviewer's side
  await page.route(/\/api\/review\/[^/?]+\/claim$/, (r) => {
    if (reviewState.claimError) return r.fulfill({ status: reviewState.claimError.status, json: reviewState.claimError.json });
    const id = r.request().url().split("/").slice(-2)[0] ?? "";
    reviewState.claimed.push(id);
    reviewState.queue = reviewState.queue.map((q) => (q.id === id ? { ...q, status: "IN_REVIEW", mine: true } : q));
    return r.fulfill({ json: { id } });
  });
  await page.route(/\/api\/review\/[^/?]+\/release$/, (r) => {
    reviewState.released.push(r.request().url().split("/").slice(-2)[0] ?? "");
    return r.fulfill({ status: 204, body: "" });
  });
  await page.route(/\/api\/review\/[^/?]+\/(original|result)$/, (r) => {
    reviewState.downloads.push(r.request().url().split("/").pop() ?? "");
    return r.fulfill({ status: 200, body: "%PDF-1.7 fake", headers: { "content-type": "application/pdf", "content-disposition": 'attachment; filename="annual-report.pdf"' } });
  });
  await page.route(/\/api\/review\/[^/?]+\/fix\/build$/, (r) => {
    reviewState.builds += 1;
    reviewState.fix = { ...(reviewState.fix ?? {}), id: "fx9", status: "QUEUED", pages: 12, result: {}, result_document_id: null, error_code: null, error_detail: null };
    return r.fulfill({ status: 202, json: reviewState.fix });
  });
  await page.route(/\/api\/review\/[^/?]+\/fix$/, (r) => {
    const plan = r.request().postDataJSON() as Record<string, unknown>;
    reviewState.fixSaved.push(plan);
    reviewState.fix = { id: "fx9", status: "DRAFT", plan, pages: null, result: {}, result_document_id: null, error_code: null, error_detail: null };
    return r.fulfill({ json: reviewState.fix });
  });
  await page.route(/\/api\/review\/[^/?]+\/submit$/, (r) => {
    if (reviewState.submitError) return r.fulfill({ status: reviewState.submitError.status, json: reviewState.submitError.json });
    reviewState.submitted.push(r.request().postDataJSON() as Record<string, unknown>);
    return r.fulfill({ json: { id: "q9", status: "COMPLETED" } });
  });
  await page.route(/\/api\/review\/[^/?]+$/, (r) => {
    if (reviewState.detailError) return r.fulfill({ status: reviewState.detailError.status, json: reviewState.detailError.json });
    // a queued build moves to running and then ready as the page polls, like the real worker
    const fx = reviewState.fix as { status?: string } | null;
    if (fx?.status === "QUEUED") reviewState.fix = { ...fx, status: "RUNNING" };
    else if (fx?.status === "RUNNING") reviewState.fix = { ...FIX_READY, id: "fx9", plan: (fx as { plan?: unknown }).plan };
    return r.fulfill({
      json: {
        review: { id: "q9", status: "IN_REVIEW", requested_at: iso(-20), due_at: iso(10), claimed_at: iso(-1), note: "Please look at the charts on page 5", pages: 12 },
        document: FIX_STATE.document,
        audit: AUDIT_DETAIL,
        findings: AUDIT_DETAIL.findings,
        structure: FIX_STATE.structure,
        fix: reviewState.fix,
      },
    });
  });
  // Registered last: the newest route is tried first, and /review/queue must not be taken for a review id.
  await page.route(/\/api\/review\/queue$/, (r) => r.fulfill({ json: { items: reviewState.queue, max_claims: 5 } }));
}
