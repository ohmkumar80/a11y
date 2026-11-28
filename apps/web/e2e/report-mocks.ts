import type { Page } from "@playwright/test";
import { SCAN_ID } from "./scan-mocks";

export const VPAT_ID = "33333333-aaaa-4bbb-8ccc-333333333333";
const LEVELS = ["Supports", "Partially Supports", "Does Not Support", "Not Applicable", "Not Evaluated"];

const crit = (id: string, name: string, level: string, over: Record<string, unknown> = {}) => ({
  id, name, level, clause: `WCAG ${id}`, conformance: "Not Evaluated", remarks: "Automated tests cannot evaluate this criterion. It needs to be evaluated by a person.",
  source: "default", failures: 0, failing_pages: 0, scanned_pages: 3, review_items: 0, automated_check_exists: false, ...over,
});

export function vpatBody(status: "DRAFT" | "SIGNED_OFF" = "DRAFT", problems: string[] = []) {
  return {
    id: VPAT_ID, scan_id: SCAN_ID, standard: "WCAG_2_2_AA", edition: "WCAG", status, levels: LEVELS, mapping_review: "draft", not_evaluated: 2, total: 3, problems,
    product: { name: "example.com", version: "", description: "", contact: "", notes: "" },
    signoff: status === "SIGNED_OFF" ? { name: "Priya N", role: "Accessibility lead", signed_at: "2026-11-27T10:00:00Z" } : null,
    signoff_text: "I have reviewed each conformance level and remark in this document and confirm that they reflect my own evaluation.",
    criteria: [
      crit("1.1.1", "Non-text Content", "A", { conformance: "Does Not Support", source: "automated", failures: 4, failing_pages: 3, automated_check_exists: true, remarks: "Automated tests found 4 failures on 3 of 3 pages scanned." }),
      crit("3.1.1", "Language of Page", "A", { automated_check_exists: true, remarks: "Automated tests found no issue for this criterion. A person must still evaluate it before it can be reported as supported." }),
      crit("1.2.5", "Audio Description (Prerecorded)", "AA"),
    ],
  };
}

const report = (id: string, kind: string, status: string, extra: Record<string, unknown> = {}) => ({
  id, scan_id: SCAN_ID, kind, standard: "WCAG_2_2_AA", status, error_code: null, error_detail: null, size_bytes: 48_000, template_version: "audit_report@v1+abc12345",
  validation: status === "READY" ? { gate: "veraPDF PDF/UA-1", passed: true } : {}, created_at: "2026-11-27T01:00:00Z", finished_at: null, vpat_id: null, ...extra,
});

export async function mockReportApi(page: Page, state: { vpat?: "DRAFT" | "SIGNED_OFF"; problems?: string[] } = {}) {
  await page.route(`**/api/scans/${SCAN_ID}/reports`, (r) => {
    if (r.request().method() === "POST") return r.fulfill({ status: 202, json: { id: "r-new", status: "QUEUED", reused: false } });
    return r.fulfill({ json: [report("r1", "audit_pdf", "READY"), report("r2", "audit_docx", "RUNNING"), report("r3", "audit_csv", "FAILED", { error_detail: "We could not produce a file that passes our accessibility checks, so we did not deliver it. Our team has been notified." }),
      report("r4", "vpat_pdf", "READY", { vpat_id: VPAT_ID })] });
  });
  await page.route("**/api/reports/r1/download", (r) => r.fulfill({ status: 200, body: "%PDF-1.7 fake", headers: { "content-type": "application/pdf", "content-disposition": 'attachment; filename="a11y-audit-example.com-2026-11-27.pdf"' } }));
  await page.route(`**/api/scans/${SCAN_ID}/vpat`, (r) => r.fulfill({ status: 201, json: { id: VPAT_ID } }));
  await page.route(`**/api/vpats/${VPAT_ID}`, (r) => {
    if (r.request().method() === "PATCH") {
      const body = r.request().postDataJSON();
      const bad = (body.criteria ?? []).find((c: { conformance?: string; remarks?: string }) => c.conformance === "Partially Supports" && !(c.remarks ?? "").trim());
      if (bad) return r.fulfill({ status: 422, json: { detail: "WCAG 1.2.5 Audio Description (Prerecorded): explain why it is 'Partially Supports'.", field: "criteria" } });
      return r.fulfill({ json: vpatBody("DRAFT") });
    }
    return r.fulfill({ json: vpatBody(state.vpat ?? "DRAFT", state.problems ?? []) });
  });
  await page.route(`**/api/vpats/${VPAT_ID}/signoff`, (r) => r.fulfill({ json: vpatBody("SIGNED_OFF") }));
  await page.route(`**/api/vpats/${VPAT_ID}/reopen`, (r) => r.fulfill({ json: vpatBody("DRAFT") }));
  await page.route(`**/api/vpats/${VPAT_ID}/export`, (r) => r.fulfill({ status: 202, json: { id: "r-new", status: "QUEUED", reused: false } }));
}
