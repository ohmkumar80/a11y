import type { Page } from "@playwright/test";

export interface MockDoc { id: string; filename: string; kind: string; size_bytes: number; status: string; reject_detail: string | null; page_count: number | null; created_at: string; expires_at: string; ready: boolean }

const doc = (id: string, filename: string, status: string, extra: Partial<MockDoc> = {}): MockDoc => ({
  id, filename, kind: filename.split(".").pop() ?? "pdf", size_bytes: 2_411_724, status, reject_detail: null, page_count: status === "CLEAN" ? 12 : null,
  created_at: "2026-11-28T08:00:00Z", expires_at: "2026-12-28T08:00:00Z", ready: status === "CLEAN", ...extra,
});

export const docState = {
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
  docState.policy.enabled = true;
}
resetDocs();

/** A new upload moves UPLOADED -> SCANNING -> CLEAN as the list is polled, like the real checker would. */
export async function mockDocumentApi(page: Page) {
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
    docState.docs = docState.docs.map((d) => (d.status === "UPLOADED" ? { ...d, status: "SCANNING" } : d.status === "SCANNING" ? { ...d, status: "CLEAN", ready: true, page_count: 3 } : d));
    return r.fulfill({ json: docState.docs });
  });
  // Registered last: Playwright tries the newest route first, and /documents/policy must not be taken for a document id.
  await page.route(/\/api\/documents\/policy$/, (r) => r.fulfill({ json: docState.policy }));
}
