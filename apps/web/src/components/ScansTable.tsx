"use client";

import NextLink from "next/link";
import { Table } from "@a11y/ui";
import { STATUS_LABEL, type ScanRow } from "@/lib/scans";
import { formatDate } from "@/lib/billing";
import { Tip } from "./Tip";

/** Recent scans. The dashboard owns the data (it also feeds the figures above), so this only draws it. */
export function ScansTable({ scans }: { scans: ScanRow[] | null }) {
  return (
    <section aria-labelledby="recent" className="flex flex-col gap-4">
      <h2 id="recent">Recent scans</h2>
      <Tip>Choose an address to open its results. “Issues found” counts everything the engines reported, including items a person still needs to judge.</Tip>
      <Table<ScanRow>
        label="Recent scans"
        rows={scans ?? []}
        rowKey={(s) => s.id}
        emptyText={scans ? "No scans yet. Start one using the form." : "Loading scans."}
        columns={[
          { id: "url", header: "Address", isRowHeader: true, render: (s) => <NextLink href={`/workspace/scan?id=${s.id}`} className="font-bold underline underline-offset-4 hover:text-accent">{s.url}</NextLink> },
          { id: "status", header: "Status", render: (s) => STATUS_LABEL[s.status] },
          { id: "pages", header: "Pages", render: (s) => s.pages_scanned },
          { id: "found", header: "Issues found", render: (s) => (s.status === "SUCCEEDED" ? s.findings_count : "Not available") },
          { id: "when", header: "Started", render: (s) => formatDate(s.created_at) },
        ]}
      />
    </section>
  );
}
