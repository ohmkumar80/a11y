"use client";

import NextLink from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { Button, ProgressBar, Select, StatusMessage, Table } from "@a11y/ui";
import { FindingDetails } from "@/components/FindingDetails";
import { ReportsPanel } from "@/components/ReportsPanel";
import { VpatStart } from "@/components/VpatStart";
import { Page } from "@/components/Page";
import { RequireAuth } from "@/components/RequireAuth";
import { get } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import {
  CONFIDENCE_LABEL, KIND_LABEL, LEGAL_LABEL, SEVERITY_ICON, SEVERITY_LABEL, STATUS_LABEL, isActive,
  type Cluster, type Finding, type Kind, type ScanDetail, type Severity,
} from "@/lib/scans";

const PAGE_SIZE = 25;
const SEVERITIES: Severity[] = ["critical", "serious", "moderate", "minor"];

function Results({ id }: { id: string }) {
  const [scan, setScan] = useState<ScanDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [standard, setStandard] = useState<string | null>(null);
  const [kind, setKind] = useState<Kind>("violation");
  const [severity, setSeverity] = useState("all");
  const [grouped, setGrouped] = useState(false);
  const [offset, setOffset] = useState(0);
  const [list, setList] = useState<{ total: number; findings?: Finding[]; clusters?: Cluster[] } | null>(null);
  const [announce, setAnnounce] = useState("");
  const allStandards = useApi<{ standards: Array<{ id: string; label: string }> }>("/standards");
  const lastMilestone = useRef("");

  const load = useCallback(async () => {
    const r = await get<ScanDetail>(`/scans/${id}${standard ? `?standard=${standard}` : ""}`);
    if (!r.ok) { setError(r.problem.detail); return; }
    setScan(r.data);
    // One polite announcement per milestone (status change, or each quarter of a crawl), never per poll.
    const q = r.data.max_pages > 1 ? Math.floor((r.data.pages_scanned / r.data.max_pages) * 4) : 0;
    const m = `${r.data.status}:${q}`;
    if (m !== lastMilestone.current) {
      lastMilestone.current = m;
      setAnnounce(r.data.status === "SUCCEEDED" ? "Scan finished." : r.data.status === "FAILED" ? "The scan failed." : r.data.status === "RUNNING" ? `Scanning: ${r.data.pages_scanned} of up to ${r.data.max_pages} pages done.` : "Scan queued.");
    }
  }, [id, standard]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!scan || !isActive(scan.status)) return;
    const t = setInterval(() => void load(), 3000);
    return () => clearInterval(t);
  }, [scan, load]);

  const done = scan?.status === "SUCCEEDED";
  useEffect(() => {
    if (!done) return;
    const q = new URLSearchParams({ kind, limit: String(PAGE_SIZE), offset: String(offset), standard: standard ?? scan!.summary.standard });
    if (severity !== "all") q.set("severity", severity);
    if (grouped) q.set("group", "cluster");
    void get<{ total: number; findings?: Finding[]; clusters?: Cluster[] }>(`/scans/${id}/findings?${q}`).then((r) => { if (r.ok) setList(r.data); });
  }, [done, id, kind, severity, grouped, offset, standard, scan]);

  if (error) return <StatusMessage>{error}</StatusMessage>;
  if (!scan) return <p role="status">Loading scan.</p>;
  const sm = scan.summary;
  const counts = scan.by_kind;
  const total = (k: Kind) => Object.values(counts[k] ?? {}).reduce((a, b) => a + b, 0);

  return (
    <div className="flex flex-col gap-8">
      <div>
        <p className="[overflow-wrap:anywhere]"><span className="font-semibold">Address:</span> {scan.url}</p>
        <p><span className="font-semibold">Status:</span> {STATUS_LABEL[scan.status]}{scan.mode === "crawl" ? `, up to ${scan.max_pages} pages` : ""}</p>
        <p className="text-sm text-fg-muted">Engines: {Object.entries(scan.engine_versions).map(([k, v]) => `${k} ${v}`).join(", ") || "not started"}. Rules {scan.rules_version ?? ""}.</p>
      </div>

      <div role="status" className="min-h-6">{announce}</div>

      {isActive(scan.status) && <ProgressBar label="Scan progress" valueText={`${scan.pages_scanned} pages done`} />}
      {scan.status === "FAILED" && (
        <StatusMessage>
          <p className="font-semibold">This scan did not finish.</p>
          <p>{scan.error_detail}</p>
          <p><NextLink href="/workspace" className="underline">Start a new scan</NextLink></p>
        </StatusMessage>
      )}

      {done && (
        <>
          <section aria-labelledby="summary" className="flex flex-col gap-3">
            <h2 id="summary" className="text-xl font-bold">Summary</h2>
            <div className="max-w-md">
              <Select label="Show results for" value={sm.standard} onChange={(k) => { setStandard(String(k)); setOffset(0); }}
                options={scan.standards.map((s) => ({ id: s, label: allStandards.data?.standards.find((x) => x.id === s)?.label ?? s.replace(/_/g, " ") }))} />
            </div>
            <p><span className="font-semibold">{sm.label}</span>. {LEGAL_LABEL[sm.legal_status] ?? sm.legal_status}.{sm.review_status === "draft" ? " The mapping of this standard is awaiting expert review." : ""}</p>
            <dl className="grid max-w-xl grid-cols-[1fr_max-content] gap-x-6 gap-y-1">
              <dt>Criteria with an automated failure</dt><dd className="font-semibold">{sm.failed.length}{sm.failed.length ? `: ${sm.failed.join(", ")}` : ""}</dd>
              <dt>Criteria with items to review</dt><dd className="font-semibold">{sm.needs_review.length}</dd>
              <dt>Automated tests found no issue</dt><dd className="font-semibold">{sm.no_issues_found.length}</dd>
              <dt>Criteria automation cannot test</dt><dd className="font-semibold">{sm.not_tested.length}</dd>
            </dl>
            <p className="max-w-2xl">Automated checks exist for {sm.automated_coverage.tested} of {sm.automated_coverage.total} criteria. {sm.disclaimer} A criterion with no automated issue still needs a person to check it.</p>
            <dl className="grid max-w-md grid-cols-[1fr_max-content] gap-x-6 gap-y-1">
              {SEVERITIES.map((s) => <div key={s} className="contents"><dt>{SEVERITY_ICON[s]} {SEVERITY_LABEL[s]} failures</dt><dd className="font-semibold">{counts.violation?.[s] ?? 0}</dd></div>)}
              <dt>Items to review</dt><dd className="font-semibold">{total("needs_review")}</dd>
              <dt>Best practices</dt><dd className="font-semibold">{total("best_practice")}</dd>
            </dl>
          </section>

          <section aria-labelledby="findings" className="flex flex-col gap-3">
            <h2 id="findings" className="text-xl font-bold">Findings</h2>
            <div className="grid max-w-3xl gap-4 sm:grid-cols-3">
              <Select label="Show" value={kind} onChange={(k) => { setKind(String(k) as Kind); setOffset(0); }} options={(Object.keys(KIND_LABEL) as Kind[]).map((k) => ({ id: k, label: KIND_LABEL[k] }))} />
              <Select label="Severity" value={severity} onChange={(k) => { setSeverity(String(k)); setOffset(0); }} options={[{ id: "all", label: "All" }, ...SEVERITIES.map((s) => ({ id: s, label: SEVERITY_LABEL[s] }))]} />
              <Select label="Group by" value={grouped ? "cluster" : "none"} onChange={(k) => { setGrouped(k === "cluster"); setOffset(0); }} options={[{ id: "none", label: "Each occurrence" }, { id: "cluster", label: "Root cause (same problem repeated)" }]} />
            </div>
            <p role="status">{list ? `${list.total} ${list.total === 1 ? "result" : "results"}.` : "Loading results."}</p>

            {grouped ? (
              <Table<Cluster>
                label="Findings grouped by root cause"
                rows={list?.clusters ?? []}
                rowKey={(c) => c.cluster_key}
                emptyText="Nothing to show with these filters."
                columns={[
                  { id: "sev", header: "Severity", render: (c) => `${SEVERITY_ICON[c.severity]} ${SEVERITY_LABEL[c.severity]}` },
                  { id: "title", header: "Problem", isRowHeader: true, render: (c) => c.title },
                  { id: "sc", header: "Criteria", render: (c) => (c.sc.length ? c.sc.join(", ") : "Best practice") },
                  { id: "n", header: "Occurrences", render: (c) => `${c.occurrences} on ${c.pages} ${c.pages === 1 ? "page" : "pages"}` },
                  { id: "sample", header: "Example", render: (c) => <code className="block max-w-xs [overflow-wrap:anywhere]">{c.sample.css}</code> },
                ]}
              />
            ) : (
              <Table<Finding>
                label="Findings"
                rows={list?.findings ?? []}
                rowKey={(f) => f.id}
                emptyText="Nothing to show with these filters."
                columns={[
                  { id: "sev", header: "Severity", render: (f) => `${SEVERITY_ICON[f.severity]} ${SEVERITY_LABEL[f.severity]}` },
                  { id: "title", header: "Problem", isRowHeader: true, render: (f) => f.title },
                  { id: "sc", header: "Criteria", render: (f) => (f.criteria.length ? f.criteria.map((c) => c.clause).join(", ") : "Best practice") },
                  { id: "conf", header: "Confidence", render: (f) => `${CONFIDENCE_LABEL[f.confidence].split(":")[0]} (${f.agreement})` },
                  { id: "el", header: "Element", render: (f) => <code className="block max-w-xs [overflow-wrap:anywhere]">{f.element.css}</code> },
                  { id: "d", header: "More", render: (f) => <FindingDetails f={f} scanId={scan.id} /> },
                ]}
              />
            )}
            {list && list.total > PAGE_SIZE && (
              <nav aria-label="Pages of results" className="flex items-center gap-3">
                <Button variant="secondary" isDisabled={offset === 0} onPress={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Previous page</Button>
                <span>Showing {offset + 1} to {Math.min(offset + PAGE_SIZE, list.total)} of {list.total}</span>
                <Button variant="secondary" isDisabled={offset + PAGE_SIZE >= list.total} onPress={() => setOffset(offset + PAGE_SIZE)}>Next page</Button>
              </nav>
            )}
          </section>
        </>
      )}

      {done && <ReportsPanel scanId={scan.id} standard={sm.standard} />}
      {done && <VpatStart scanId={scan.id} standard={sm.standard} />}

      {scan.pages.length > 1 && (
        <section aria-labelledby="pages" className="flex flex-col gap-3">
          <h2 id="pages" className="text-xl font-bold">Pages scanned</h2>
          <Table<ScanDetail["pages"][number]>
            label="Pages scanned" rows={scan.pages} rowKey={(p) => p.id}
            columns={[
              { id: "u", header: "Address", isRowHeader: true, render: (p) => <span className="[overflow-wrap:anywhere]">{p.url}</span> },
              { id: "s", header: "Result", render: (p) => (p.status === "OK" ? "Scanned" : p.error_detail ?? p.status) },
            ]}
          />
        </section>
      )}
    </div>
  );
}

function Content() {
  const id = useSearchParams().get("id");
  return id ? <Results id={id} /> : <StatusMessage>No scan was chosen. <NextLink href="/workspace" className="underline">Go to your scans</NextLink>.</StatusMessage>;
}

export default function ScanPage() {
  return (
    <RequireAuth>
      {() => (
        <Page title="Scan results" intro="Problems found by three accessibility engines, merged so each problem appears once.">
          <p><NextLink href="/workspace" className="underline">Back to your scans</NextLink></p>
          <Suspense><Content /></Suspense>
        </Page>
      )}
    </RequireAuth>
  );
}
