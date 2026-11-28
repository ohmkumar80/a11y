import type { Page } from "@playwright/test";

export interface MockDoc { id: string; filename: string; kind: string; size_bytes: number; status: string; reject_detail: string | null; page_count: number | null; created_at: string; expires_at: string; ready: boolean; latest_audit: unknown }

const doc = (id: string, filename: string, status: string, extra: Partial<MockDoc> = {}): MockDoc => ({
  id, filename, kind: filename.split(".").pop() ?? "pdf", size_bytes: 2_411_724, status, reject_detail: null, page_count: status === "CLEAN" ? 12 : null,
  created_at: "2026-11-28T08:00:00Z", expires_at: "2026-12-28T08:00:00Z", ready: status === "CLEAN", latest_audit: null, ...extra,
});

const finding = (id: string, severity: string, title: string, extra: Record<string, unknown> = {}) => ({
  id, rule_id: "7.3-1", source: "verapdf", severity, title, explanation: "A screen reader user cannot tell what an image shows unless it has a text description.",
  how_to_fix: "Add alternative text to each meaningful image.", wcag: ["1.1.1"], needs_human: false, count: 1, pages: [], pages_total: 0, examples: [], explained: true, ...extra,
});
export const AUDIT_DONE = {
  id: "a1", document_id: "d1", standard: "PDF_UA_1", status: "SUCCEEDED", pages: 12, error_code: null, error_detail: null, created_at: "2026-11-28T09:00:00Z", finished_at: "2026-11-28T09:00:20Z",
  summary: {
    standard: "PDF/UA-1", verdict: "problems_found", findings: 3, by_severity: { critical: 1, serious: 1, moderate: 1, minor: 0 }, needs_a_person: 1, rules_passed: 90, rules_failed: 3,
    caveat: "Automated checks find only part of what makes a PDF accessible. They cannot judge whether alternative text is meaningful, so a person still needs to review the file.",
    facts: { pages: 12, tagged: true, has_structure: true, language: null, has_title: true, has_bookmarks: false, image_only_pages: 2 },
  },
};
export const AUDIT_DETAIL = {
  ...AUDIT_DONE,
  document: { id: "d1", filename: "annual-report.pdf", kind: "pdf", page_count: 12 },
  findings: [
    finding("f1", "critical", "Some pages are pictures of text (scanned pages)", { rule_id: "direct:image-only-pages", source: "direct", pages: [3, 4], pages_total: 2, count: 2, how_to_fix: "Run text recognition (OCR) on the file." }),
    finding("f2", "serious", "Images have no alternative text", { needs_human: true, count: 4, pages: [1, 2, 5], pages_total: 3, examples: [{ where: "root/document[0]/StructTreeRoot[0]/K[0]/Figure", message: "Figure tag has no alternative text" }] }),
    finding("f3", "moderate", "Heading levels are skipped or do not start at level 1", { rule_id: "7.4.2-1", wcag: ["1.3.1", "2.4.6"] }),
  ],
};

export const docState = {
  auditsStarted: [] as string[],
  auditError: null as null | { status: number; json: Record<string, unknown> },
  auditDetail: AUDIT_DETAIL as Record<string, unknown>,
  docs: [] as MockDoc[],
  uploads: [] as { filename: string; bytes: number }[],
  deleted: [] as string[],
  downloads: [] as string[],
  uploadError: null as null | { status: number; json: Record<string, unknown> },
  policy: { enabled: true, kinds: [{ kind: "pdf", max_mb: 50 }, { kind: "docx", max_mb: 25 }], max_pages: 500, retention_days: 30 },
};

export function resetDocs() {
  docState.docs = [
    doc("d1", "annual-report.pdf", "CLEAN"),
    doc("d2", "scan-copy.pdf", "REJECTED", { reject_detail: "That PDF is password-protected. Remove the password and upload it again." }),
    doc("d3", "board-pack.docx", "FAILED", { reject_detail: "We could not finish checking this file because of a problem on our side. Nothing was charged. Please try again later." }),
  ];
  docState.uploads = [];
  docState.deleted = [];
  docState.downloads = [];
  docState.uploadError = null;
  docState.auditsStarted = [];
  docState.auditError = null;
  docState.auditDetail = AUDIT_DETAIL;
  docState.policy.enabled = true;
}
resetDocs();

/** A new upload moves UPLOADED -> SCANNING -> CLEAN as the list is polled, like the real checker would. */
export async function mockDocumentApi(page: Page) {
  await page.route(/\/api\/documents\/[^/?]+\/audits$/, (r) => {
    if (docState.auditError) return r.fulfill({ status: docState.auditError.status, json: docState.auditError.json });
    const id = r.request().url().split("/").slice(-2)[0] ?? "";
    docState.auditsStarted.push(id);
    docState.docs = docState.docs.map((d) => (d.id === id ? { ...d, latest_audit: { ...AUDIT_DONE, status: "RUNNING", summary: {} } } : d));
    return r.fulfill({ status: 202, json: { ...AUDIT_DONE, status: "QUEUED", summary: {} } });
  });
  await page.route(/\/api\/documents\/[^/?]+\/audits\/[^/?]+$/, (r) => r.fulfill({ json: docState.auditDetail }));
  await page.route(/\/api\/documents\/[^/?]+\/download$/, (r) => {
    docState.downloads.push(r.request().url().split("/").slice(-2)[0] ?? "");
    return r.fulfill({ status: 200, body: "%PDF-1.7 fake", headers: { "content-type": "application/pdf", "content-disposition": 'attachment; filename="annual-report.pdf"' } });
  });
  await page.route(/\/api\/documents\/[^/?]+$/, (r) => {
    const id = r.request().url().split("/").pop() ?? "";
    if (r.request().method() === "DELETE") {
      docState.deleted.push(id);
      docState.docs = docState.docs.filter((d) => d.id !== id);
      return r.fulfill({ status: 204, body: "" });
    }
    return r.fulfill({ json: docState.docs.find((d) => d.id === id) });
  });
  await page.route(/\/api\/documents(\?.*)?$/, (r) => {
    if (r.request().method() === "POST") {
      if (docState.uploadError) return r.fulfill({ status: docState.uploadError.status, json: docState.uploadError.json });
      const name = new URL(r.request().url()).searchParams.get("filename") ?? "file";
      docState.uploads.push({ filename: name, bytes: r.request().postDataBuffer()?.length ?? 0 });
      const d = doc(`new-${docState.uploads.length}`, name, "UPLOADED", { created_at: new Date().toISOString() });
      docState.docs = [d, ...docState.docs];
      return r.fulfill({ status: 202, json: d });
    }
    docState.docs = docState.docs.map((d) => ((d.latest_audit as { status?: string } | null)?.status === "RUNNING" ? { ...d, latest_audit: AUDIT_DONE } : d));
    docState.docs = docState.docs.map((d) => (d.status === "UPLOADED" ? { ...d, status: "SCANNING" } : d.status === "SCANNING" ? { ...d, status: "CLEAN", ready: true, page_count: 3 } : d));
    return r.fulfill({ json: docState.docs });
  });
  // Registered last: Playwright tries the newest route first, and /documents/policy must not be taken for a document id.
  await page.route(/\/api\/documents\/policy$/, (r) => r.fulfill({ json: docState.policy }));
}
