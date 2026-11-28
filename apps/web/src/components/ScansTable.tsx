"use client";

import NextLink from "next/link";
import { useEffect } from "react";
import { Table } from "@a11y/ui";
import { STATUS_LABEL, isActive, type ScanRow } from "@/lib/scans";
import { formatDate } from "@/lib/billing";
import { useApi } from "@/lib/useApi";

export function ScansTable() {
  const { data, reload } = useApi<{ total: number; scans: ScanRow[] }>("/scans?limit=25");
  const anyActive = data?.scans.some((s) => isActive(s.status));
  // Refresh quietly while something is running; the table itself is not a live region (no chatter).
  useEffect(() => {
    if (!anyActive) return;
    const t = setInterval(() => void reload(), 4000);
    return () => clearInterval(t);
  }, [anyActive, reload]);

  return (
    <section aria-labelledby="recent" className="flex flex-col gap-3">
      <h2 id="recent" className="text-xl font-bold">Recent scans</h2>
      <Table<ScanRow>
        label="Recent scans"
        rows={data?.scans ?? []}
        rowKey={(s) => s.id}
        emptyText={data ? "No scans yet. Start one above." : "Loading scans."}
        columns={[
          { id: "url", header: "Address", isRowHeader: true, render: (s) => <NextLink href={`/workspace/scan?id=${s.id}`} className="underline">{s.url}</NextLink> },
          { id: "status", header: "Status", render: (s) => STATUS_LABEL[s.status] },
          { id: "pages", header: "Pages", render: (s) => s.pages_scanned },
          { id: "found", header: "Issues found", render: (s) => (s.status === "SUCCEEDED" ? s.findings_count : "Not available") },
          { id: "when", header: "Started", render: (s) => formatDate(s.created_at) },
        ]}
      />
    </section>
  );
}
