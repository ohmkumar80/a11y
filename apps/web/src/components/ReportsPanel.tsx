"use client";

import { useEffect, useRef, useState } from "react";
import { Button, StatusMessage, Table, notify } from "@a11y/ui";
import { download, post } from "@/lib/api";
import { formatDate } from "@/lib/billing";
import { KIND_LABEL, REPORT_STATUS, formatSize, type Report, type ReportKind } from "@/lib/reports";
import { useApi } from "@/lib/useApi";

const AUDIT: ReportKind[] = ["audit_pdf", "audit_docx", "audit_csv"];

/** Create, track and download reports for a finished scan. Status is polled quietly; the table is not a live region, and each
 *  finished or failed report is announced once through a polite status message. */
export function ReportsPanel({ scanId, standard, vpatId }: { scanId: string; standard: string; vpatId?: string }) {
  const { data, reload } = useApi<Report[]>(`/scans/${scanId}/reports`);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [announce, setAnnounce] = useState("");
  const seen = useRef<Record<string, string>>({});
  const rows = (data ?? []).filter((r) => (vpatId ? r.vpat_id === vpatId : r.vpat_id === null));
  const active = rows.some((r) => r.status === "QUEUED" || r.status === "RUNNING");

  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => void reload(), 3000);
    return () => clearInterval(t);
  }, [active, reload]);

  useEffect(() => {
    for (const r of rows) {
      const prev = seen.current[r.id];
      seen.current[r.id] = r.status;
      if (prev && prev !== r.status && (r.status === "READY" || r.status === "FAILED")) {
        setAnnounce(r.status === "READY" ? `${KIND_LABEL[r.kind]} is ready to download.` : `${KIND_LABEL[r.kind]} could not be prepared.`);
      }
    }
  }, [rows]);

  async function create(kind: ReportKind) {
    setBusy(kind);
    setError(null);
    const r = vpatId
      ? await post(`/vpats/${vpatId}/export`, { format: kind === "vpat_docx" ? "docx" : "pdf" })
      : await post(`/scans/${scanId}/reports`, { kind, standard });
    setBusy(null);
    if (!r.ok) { setError(r.problem.detail); return; }
    notify({ title: "Report requested", description: "We will tell you when it is ready.", kind: "success" });
    void reload();
  }

  const kinds: ReportKind[] = vpatId ? ["vpat_pdf", "vpat_docx"] : AUDIT;
  return (
    <section aria-labelledby="reports" className="flex flex-col gap-3">
      <h2 id="reports" className="text-xl font-bold">{vpatId ? "Exports" : "Reports"}</h2>
      <p className="max-w-2xl text-fg-muted">
        Every file is checked for accessibility before you can download it. PDFs are tested against PDF/UA, Word files for headings, table headers, title and language.
        A file that fails the check is never offered.
      </p>
      <div className="flex flex-wrap gap-3">
        {kinds.map((k) => (
          <Button key={k} variant="secondary" isPending={busy === k} pendingLabel={`Requesting ${KIND_LABEL[k]}`} onPress={() => void create(k)}>
            Create {KIND_LABEL[k]}
          </Button>
        ))}
      </div>
      {error && <StatusMessage>{error}</StatusMessage>}
      <div role="status" className="min-h-6">{announce}</div>
      <Table<Report>
        label={vpatId ? "Exports of this VPAT" : "Reports for this scan"}
        rows={rows}
        rowKey={(r) => r.id}
        emptyText={data ? "No reports yet." : "Loading reports."}
        columns={[
          { id: "kind", header: "Report", isRowHeader: true, render: (r) => KIND_LABEL[r.kind] },
          { id: "std", header: "Standard", render: (r) => r.standard.replace(/_/g, " ") },
          { id: "status", header: "Status", render: (r) => (r.status === "FAILED" ? `${REPORT_STATUS[r.status]}: ${r.error_detail ?? ""}` : REPORT_STATUS[r.status]) },
          { id: "check", header: "Accessibility check", render: (r) => (r.status === "READY" ? `Passed (${r.validation.gate ?? "checked"})` : "Not yet") },
          { id: "when", header: "Created", render: (r) => `${formatDate(r.created_at)} ${formatSize(r.size_bytes)}`.trim() },
          {
            id: "dl", header: "Download",
            render: (r) => r.status === "READY" ? (
              <Button variant="secondary" onPress={async () => {
                const res = await download(`/reports/${r.id}/download`);
                if (!res.ok) setError(res.problem.detail); else setAnnounce(`${KIND_LABEL[r.kind]} downloaded.`);
              }}>Download<span className="a11y-sr-only"> {KIND_LABEL[r.kind]}, created {formatDate(r.created_at)}</span></Button>
            ) : null,
          },
        ]}
      />
    </section>
  );
}
