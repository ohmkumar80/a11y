"use client";

import NextLink from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { Button, ProgressBar, Select, StatusMessage, Table } from "@a11y/ui";
import { FindingDetails } from "@/components/FindingDetails";
import { ReportsPanel } from "@/components/ReportsPanel";
import { VpatStart } from "@/components/VpatStart";
import { Page } from "@/components/Page";
import { SeverityBadge, severityStat } from "@/components/SeverityBadge";
import { RequireAuth } from "@/components/RequireAuth";
import { get } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import {
  CONFIDENCE_LABEL, KIND_LABEL, LEGAL_LABEL, SEVERITY_ICON, SEVERITY_LABEL, STATUS_LABEL, isActive,
  type Cluster, type Finding, type Kind, type ScanDetail, type Severity,
} from "@/lib/scans";

const PAGE_SIZE = 25;
const SEVERITIES: Severity[] = ["critical", "serious", "moderate", "minor"];

function Stat({ label, value, note, tone = "border-fg bg-bg text-fg" }: { label: string; value: number; note?: string; tone?: string }) {
  return (
    <div className={`flex flex-col gap-1 border-2 p-4 ${tone}`}>
      <dd className="order-1 font-display text-5xl font-semibold leading-none">{value}</dd>
      <dt className="order-2 text-sm font-medium">{label}</dt>
      {note && <dd className="order-3 text-sm [overflow-wrap:anywhere]">{note}</dd>}
    </div>
  );
}

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
    <div className="a11y-stack flex flex-col gap-8">
      <div className="a11y-boxed flex flex-col gap-1.5 p-5 sm:p-6">
        <p className="[overflow-wrap:anywhere] text-lg"><span className="font-semibold">Address:</span> {scan.url}</p>
        <p><span className="font-semibold">Status:</span> <span className="ml-1 inline-flex border-[1.5px] border-fg bg-accent-subtle px-2 py-0.5 text-sm font-bold">{STATUS_LABEL[scan.status]}</span>{scan.mode === "crawl" ? `, up to ${scan.max_pages} pages` : ""}</p>
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
            <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Stat label="Criteria with an automated failure" value={sm.failed.length} note={sm.failed.length ? sm.failed.join(", ") : undefined} />
              <Stat label="Criteria with items to review" value={sm.needs_review.length} />
              <Stat label="Automated tests found no issue" value={sm.no_issues_found.length} />
              <Stat label="Criteria automation cannot test" value={sm.not_tested.length} />
            </dl>
            <p className="max-w-2xl">Automated checks exist for {sm.automated_coverage.tested} of {sm.automated_coverage.total} criteria. {sm.disclaimer} A criterion with no automated issue still needs a person to check it.</p>
            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              {SEVERITIES.map((s) => <Stat key={s} tone={severityStat(s)} label={`${SEVERITY_ICON[s]} ${SEVERITY_LABEL[s]} failures`} value={counts.violation?.[s] ?? 0} />)}
              <Stat label="Items to review" value={total("needs_review")} />
              <Stat label="Best practices" value={total("best_practice")} />
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
                  { id: "sev", header: "Severity", render: (c) => <SeverityBadge severity={c.severity} /> },
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
                  { id: "sev", header: "Severity", render: (f) => <SeverityBadge severity={f.severity} /> },
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

      {done && (
        <p className="a11y-note text-lg">
          <NextLink href={`/workspace/scan/workbench?id=${scan.id}`} className="font-bold underline underline-offset-4 hover:text-accent">Open the Fix Workbench</NextLink>
          {" "}to go through the problems one by one, with a screenshot and a checked code fix for each.
        </p>
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
