"use client";

import { useState } from "react";
import { Button, StatusMessage, Table, notify } from "@a11y/ui";
import { post } from "@/lib/api";
import { formatDate } from "@/lib/billing";
import { useApi } from "@/lib/useApi";

interface Failed { id: string; organization: string; kind: string; size_bytes: number; created_at: string; attempts: number; why: string | null }
interface Overview {
  health: { scanner: "ok" | "down"; storage: "ok" | "down" };
  by_status: Record<string, number>;
  rejections_30d: { code: string; count: number }[];
  stored_bytes: number;
  expired_waiting: number;
  stuck: number;
  failed: Failed[];
}

const STATUS_LABEL: Record<string, string> = {
  UPLOADED: "Waiting to be checked", SCANNING: "Being checked", CLEAN: "Passed all checks",
  REJECTED: "Refused (the customer's file)", FAILED: "Could not be checked (our side)", DELETED: "Erased",
};
const REASON: Record<string, string> = {
  malware: "Virus found", encrypted: "Password-protected", active_content: "Scripts or macros", zip_bomb: "Zip bomb",
  zip_unsafe_path: "Unsafe paths inside", zip_nested: "Programs or archives inside", xml_entities: "XML entity attack",
  too_many_pages: "Too many pages", corrupt: "Damaged file", system_fault: "Our scanner or store was down",
};
const mb = (b: number) => (b >= 1073741824 ? `${(b / 1073741824).toFixed(1)} GB` : `${(b / 1048576).toFixed(1)} MB`);

/** The document pipeline at a glance. Limits, file types, retention and the safety policy are ordinary settings
 *  (Settings tab: documents.uploads, documents.safety, documents.retention), so they are versioned and audited. */
export function DocumentsTab() {
  const ov = useApi<Overview>("/admin/documents/overview");
  const [busy, setBusy] = useState(false);
  if (ov.error) return <StatusMessage>{ov.error.detail}</StatusMessage>;
  if (!ov.data) return <p role="status">Loading the documents overview.</p>;
  const d = ov.data;
  const healthy = d.health.scanner === "ok" && d.health.storage === "ok";

  async function retry(id: string) {
    setBusy(true);
    const r = await post(`/admin/documents/${id}/rescan`);
    setBusy(false);
    if (r.ok) { notify({ title: "The file will be checked again", kind: "success" }); void ov.reload(); } else notify({ title: r.problem.detail, kind: "error" });
  }
  async function sweep() {
    setBusy(true);
    const r = await post<{ erased: number; errors: number }>("/admin/documents/purge");
    setBusy(false);
    if (r.ok) { notify({ title: `${r.data.erased} expired file${r.data.erased === 1 ? "" : "s"} erased${r.data.errors ? `, ${r.data.errors} could not be erased` : ""}`, kind: "success" }); void ov.reload(); } else notify({ title: r.problem.detail, kind: "error" });
  }

  return (
    <div className="a11y-page-body flex flex-col gap-8">
      <section aria-labelledby="docs-health" className="flex flex-col gap-2">
        <h2 id="docs-health" className="text-xl font-bold">{healthy ? "✓ Uploads are being checked" : "! Uploads are being held back"}</h2>
        <p>Virus scanner: {d.health.scanner === "ok" ? "working" : "not reachable"}. File store: {d.health.storage === "ok" ? "working" : "not reachable"}. {!healthy && "Files stay unreadable until both work; nothing is let through unchecked."}</p>
        <p>
          Stored: {mb(d.stored_bytes)}. Waiting past their retention: {d.expired_waiting}. Stuck for over 15 minutes: {d.stuck}.{" "}
          <Button variant="secondary" onPress={() => void ov.reload()}>Refresh</Button>{" "}
          <Button variant="secondary" isDisabled={busy} onPress={() => void sweep()}>Erase expired files now</Button>
        </p>
        <p className="max-w-prose text-fg-muted">To change file types, size and page limits, retention or the safety policy, use the Settings tab: documents.uploads, documents.safety and documents.retention. Each can be set for everyone, one plan or one organisation, is versioned and can be rolled back. The feature itself can be switched off with the “documents” flag.</p>
      </section>

      <section aria-labelledby="docs-status" className="flex flex-col gap-3">
        <h2 id="docs-status" className="text-xl font-bold">Where files are</h2>
        <dl className="grid max-w-xl grid-cols-[1fr_max-content] gap-x-6 gap-y-1">
          {Object.entries(d.by_status).map(([s, n]) => <div key={s} className="contents"><dt>{STATUS_LABEL[s] ?? s}</dt><dd className="font-semibold">{n}</dd></div>)}
        </dl>
      </section>

      <section aria-labelledby="docs-why" className="flex flex-col gap-3">
        <h2 id="docs-why" className="text-xl font-bold">Why files were refused in the last 30 days</h2>
        <Table<{ code: string; count: number }>
          label="Reasons files were refused"
          rows={d.rejections_30d}
          rowKey={(r) => r.code ?? "none"}
          emptyText="No files were refused in the last 30 days."
          columns={[
            { id: "r", header: "Reason", isRowHeader: true, render: (r) => REASON[r.code] ?? r.code ?? "Unknown" },
            { id: "n", header: "Files", render: (r) => String(r.count) },
          ]}
        />
      </section>

      <section aria-labelledby="docs-failed" className="flex flex-col gap-3">
        <h2 id="docs-failed" className="text-xl font-bold">Files we could not check</h2>
        <p className="max-w-prose text-fg-muted">These failed because of a problem on our side, and nothing was charged. After fixing the scanner or the store, try them again. They still have to pass every check before anyone can read them.</p>
        {d.failed.length === 0 ? (
          <p>No files are waiting for a retry.</p>
        ) : (
          // A list, not a table: buttons inside a data grid cannot be reached with the Tab key, and retrying must be keyboard friendly.
          <ul aria-label="Files we could not check" className="flex max-w-3xl flex-col gap-3">
            {d.failed.map((f) => (
              <li key={f.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border-2 border-border-subtle p-3">
                <span>
                  <strong>{f.organization}</strong>: {f.kind.toUpperCase()}, {mb(f.size_bytes)}, uploaded {formatDate(f.created_at)}
                  <span className="block text-sm text-fg-muted">Why: {f.why ?? "unknown"}. Checked {f.attempts} time{f.attempts === 1 ? "" : "s"}.</span>
                </span>
                <Button variant="secondary" isDisabled={busy} onPress={() => void retry(f.id)}>
                  Try again<span className="a11y-sr-only"> for the {f.kind.toUpperCase()} from {f.organization}</span>
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
