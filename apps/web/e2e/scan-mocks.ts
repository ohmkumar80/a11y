import type { Page } from "@playwright/test";

const standards = [
  { id: "WCAG_2_2_AA", label: "WCAG 2.2 Level AA", legal_status: "reference", criteria_count: 55, automated_criteria: 30, citation: null },
  { id: "EU_EAA_EN_301_549", label: "EU European Accessibility Act (EN 301 549)", legal_status: "regulation", criteria_count: 50, automated_criteria: 28, citation: "EN 301 549" },
  { id: "US_ADA_TITLE_III", label: "US ADA Title III (private businesses)", legal_status: "benchmark", criteria_count: 50, automated_criteria: 28, citation: null },
];

export const SCAN_ID = "11111111-aaaa-4bbb-8ccc-111111111111";
export const FINDING = {
  id: "f1", rule: "image-alt", title: "Images need a text alternative", kind: "violation", severity: "critical", confidence: "high",
  criteria: [{ id: "1.1.1", name: "Non-text Content", level: "A", clause: "WCAG 1.1.1" }], engines: ["axe", "ibm", "htmlcs"], agreement: "3 of 3 engines",
  message: "Element does not have an alt attribute", element: { xpath: "/html[1]/body[1]/img[1]", css: "html > body > img:nth-of-type(1)", tag: "img", html: '<img src="logo.png">', rect: { x: 100, y: 200, w: 300, h: 80 } },
  page: { id: "p1", url: "https://example.com/" }, help_url: "https://dequeuniversity.com/rules/axe/4.14/image-alt", cluster_key: "abc",
};
export const FINDING2 = {
  ...FINDING, id: "f2", rule: "button-name", title: "Buttons need a name", severity: "serious", criteria: [{ id: "4.1.2", name: "Name, Role, Value", level: "A", clause: "WCAG 4.1.2" }],
  element: { xpath: "/html[1]/body[1]/button[1]", css: "html > body > button:nth-of-type(1)", tag: "button", html: "<button></button>", rect: { x: 0, y: 0, w: 0, h: 0 } },
};
export const PAGE_SHOT = { width: 1280, height: 1000, page_height: 2400, truncated: true };
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64");
const detail = (status: string, pages = 1) => ({
  id: SCAN_ID, url: "https://example.com/", mode: "single", max_pages: 1, standards: ["WCAG_2_2_AA", "EU_EAA_EN_301_549"], status, error_code: null, error_detail: null,
  pages_scanned: pages, findings_count: 3, created_at: "2026-11-27T01:00:00Z", started_at: null, finished_at: null,
  engine_versions: { axe: "4.14.1", ibm: "4.0.35", htmlcs: "2.5.1" }, rules_version: "2026-11-27.1", attempts: 1,
  pages: [{ id: "p1", url: "https://example.com/", status: "OK", error_detail: null, title: "Example", screenshot: PAGE_SHOT }],
  by_kind: { violation: { critical: 1, serious: 1 }, needs_review: { moderate: 2 }, best_practice: { minor: 1 } },
  summary: { standard: "WCAG_2_2_AA", label: "WCAG 2.2 Level AA", legal_status: "reference", citation: null, notes: null, automated_coverage: { tested: 30, total: 55 },
    failed: ["1.1.1", "4.1.2"], needs_review: ["1.4.3"], no_issues_found: ["3.1.1"], not_tested: ["1.2.5"], review_status: "draft",
    disclaimer: "Automated tests cover only part of WCAG. This is not a statement of conformance." },
});

export const GUIDANCE = {
  rule: "image-alt", review_status: "draft", summary: "Every image that carries information needs a short text description.",
  why: "A screen reader reads the alt text aloud in place of the image.", who: ["Blind and low-vision people using screen readers"],
  steps: ["Decide whether the image carries information.", "Write what it conveys in a short phrase."],
  examples: [{ stack: "html", before: '<img src="a.png">', after: '<img src="a.png" alt="Sales chart">' }, { stack: "react", before: "<img src={a} />", after: '<img src={a} alt="Sales chart" />' }],
  links: [{ title: "1.1.1 Non-text Content", url: "https://www.w3.org/WAI/WCAG22/Understanding/non-text-content.html" }],
  how_to_check: "Move to the image with a screen reader.", machine_checked: true,
};
export const SCANS = [
  { ...detail("SUCCEEDED"), pages: undefined },
  { ...detail("RUNNING", 0), id: "22222222-aaaa-4bbb-8ccc-222222222222", url: "https://shop.example.com/", pages: undefined },
];

/** Mocks the scan, standards and domain endpoints. `state` lets a test pick what a scan looks like. */
export async function mockScanApi(page: Page, state: { status?: string } = {}) {
  await page.route("**/api/rules/*/guidance", (r) => {
    if (r.request().url().includes("/image-alt/")) return r.fulfill({ json: GUIDANCE });
    return r.fulfill({ status: 404, json: { detail: "No guidance for this rule yet." } });
  });
  await page.route("**/api/standards", (r) => r.fulfill({ json: { review: { status: "draft" }, standards } }));
  await page.route("**/api/domains", (r) => r.fulfill({ json: [{ id: "d1", host: "example.com", verified: false, method: null, instructions: { file: { url: "https://example.com/.well-known/a11y-verification.txt", content: "a11y-token" }, meta: { tag: '<meta name="a11y-verification" content="a11y-token">' } } }] }));
  await page.route("**/api/scans?*", (r) => r.fulfill({ json: { total: 2, scans: SCANS } }));
  await page.route("**/api/scans", (r) => {
    if (r.request().method() === "POST") return r.fulfill({ status: 202, json: { id: SCAN_ID, status: "QUEUED", max_pages: 1 } });
    return r.fulfill({ json: { total: 2, scans: SCANS } });
  });
  await page.route(`**/api/scans/${SCAN_ID}/findings?*`, (r) => {
    const u = new URL(r.request().url());
    if (u.searchParams.get("group") === "cluster")
      return r.fulfill({ json: { total: 1, clusters: [{ cluster_key: "abc", rule: "image-alt", title: "Images need a text alternative", sc: ["1.1.1"], occurrences: 40, pages: 12, severity: "critical", sample: { id: "f1", html: "<img>", css: "ul > li > img" } }] } });
    if (u.searchParams.get("limit") === "100") return r.fulfill({ json: { total: 2, findings: [FINDING, FINDING2] } }); // the Fix Workbench
    return r.fulfill({ json: { total: 1, findings: [FINDING] } });
  });
  await page.route(`**/api/scans/${SCAN_ID}/pages/p1/screenshot`, (r) => r.fulfill({ status: 200, contentType: "image/png", body: PNG }));
  await page.route(`**/api/scans/${SCAN_ID}`, (r) => r.fulfill({ json: detail(state.status ?? "SUCCEEDED") }));
  await page.route(`**/api/scans/${SCAN_ID}?*`, (r) => r.fulfill({ json: detail(state.status ?? "SUCCEEDED") }));
}

export const FIX_ID = "22222222-aaaa-4bbb-8ccc-222222222222";
const fixBase = { id: FIX_ID, finding_id: "f1", rule: "button-name", original_html: "<button></button>", explanation: "", notes: [], checks: [], reason: null, detail: null, model_id: null, attempts: 0, from_cache: false, rung: null, fixed_html: null };
export const FIX_READY = {
  ...fixBase, status: "READY", rung: "light", model_id: "m-light", attempts: 1,
  fixed_html: '<button aria-label="Close"></button>', explanation: "Gives the button a name so screen readers can say what it does.",
  notes: ["Written by an AI model: read it before you use it."],
  checks: [{ name: "The fix is valid HTML", passed: true, detail: "" }, { name: "The problem no longer appears in our checks", passed: true, detail: "" }, { name: "The fix creates no new problems", passed: true, detail: "" }],
};
export const FIX_NO_MODEL = { ...fixBase, status: "NEEDS_REVIEW", reason: "ai_unavailable", detail: "No AI model is available for this right now, and there is no ready-made fix for this rule." };

/** First POST returns PENDING; the next poll returns `final`. A retry POST (retry: true) starts again and returns `afterRetry`. */
export async function mockFixApi(page: Page, final: object, afterRetry?: object) {
  let phase: "idle" | "pending" | "retry" = "idle";
  await page.route(`**/api/scans/${SCAN_ID}/findings/*/fix`, (r) => {
    const body = r.request().postDataJSON() as { retry?: boolean };
    phase = body?.retry ? "retry" : "pending";
    return r.fulfill({ status: 202, json: { ...fixBase, status: "PENDING" } });
  });
  await page.route(`**/api/fixes/${FIX_ID}`, (r) => r.fulfill({ json: phase === "retry" && afterRetry ? afterRetry : final }));
}
