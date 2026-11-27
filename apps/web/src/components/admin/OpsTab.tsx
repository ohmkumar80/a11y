"use client";

import { useState } from "react";
import { Button, Dialog, DialogTrigger, StatusMessage, Table } from "@a11y/ui";
import { get } from "@/lib/api";
import { formatDate } from "@/lib/billing";
import { useApi } from "@/lib/useApi";
import { Markdown } from "./Markdown";

interface Canary { key: string; label: string; state: "ok" | "failing" | "stale" | "never"; at: string | null; detail: string; duration_ms: number | null }
interface Incident { key: string; severity: "critical" | "warning" | "info"; title: string; count: number; detail: string; runbook: string }
interface Ops {
  generated_at: string; status: "ok" | "degraded" | "down"; health: Record<string, string>; queues: Record<string, number | null>;
  canaries: Canary[]; incidents: Incident[]; stats: Record<string, number>;
}

const STATUS = { ok: "All systems are working", degraded: "Working, with warnings", down: "There are problems that need attention" } as const;
const SEVERITY = { critical: "Critical", warning: "Warning", info: "For information" } as const;
const CANARY = { ok: "Working", failing: "Failing", stale: "Not reporting", never: "Has not reported yet" } as const;
const STAT_LABEL: Record<string, string> = {
  scans_24h: "Scans started", scans_succeeded_24h: "Scans finished successfully", reports_ready_24h: "Reports produced", emails_sent_24h: "Emails sent",
  webhooks_delivered_24h: "Webhook deliveries", ai_calls_24h: "AI calls",
};

function Runbook({ slug, title }: { slug: string; title: string }) {
  const [md, setMd] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  async function open() {
    const r = await get<{ markdown: string }>(`/admin/ops/runbooks/${slug}`);
    if (r.ok) setMd(r.data.markdown); else setErr(r.problem.detail);
  }
  return (
    <DialogTrigger onOpenChange={(o) => { if (o) void open(); }}>
      <Button variant="secondary">Runbook<span className="a11y-sr-only"> for {title}</span></Button>
      <Dialog title={`Runbook: ${title}`}>
        {err ? <StatusMessage>{err}</StatusMessage> : md === null ? <p role="status">Loading.</p> : <Markdown source={md} base={3} />}
      </Dialog>
    </DialogTrigger>
  );
}

/** A read-only view of how the platform is doing. It never changes anything; refresh it by hand. */
export function OpsTab() {
  const ops = useApi<Ops>("/admin/ops");
  if (ops.error) return <StatusMessage>{ops.error.detail}</StatusMessage>;
  if (!ops.data) return <p role="status">Loading the operations overview.</p>;
  const d = ops.data;
  return (
    <div className="flex flex-col gap-8">
      <section aria-labelledby="ops-status" className="flex flex-col gap-2">
        <h2 id="ops-status" className="text-xl font-bold">{d.status === "ok" ? "✓ " : d.status === "degraded" ? "! " : "✗ "}{STATUS[d.status]}</h2>
        <p>Updated {formatDate(d.generated_at)}. This page only reads; nothing here changes the system. <Button variant="secondary" onPress={() => void ops.reload()}>Refresh</Button></p>
        <p>Database: {d.health.postgres === "ok" ? "working" : "not reachable"}. Redis: {d.health.redis === "ok" ? "working" : "not reachable"}.</p>
      </section>

      <section aria-labelledby="ops-incidents" className="flex flex-col gap-3">
        <h2 id="ops-incidents" className="text-xl font-bold">Incidents</h2>
        <Table<Incident>
          label="Incidents"
          rows={d.incidents}
          rowKey={(i) => i.key}
          emptyText="No incidents. Everything this page checks looks normal."
          columns={[
            { id: "t", header: "What", isRowHeader: true, render: (i) => <>{i.title}{i.detail && <span className="block text-sm text-fg-muted">{i.detail}</span>}</> },
            { id: "s", header: "Severity", render: (i) => SEVERITY[i.severity] },
            { id: "n", header: "Count", render: (i) => String(i.count) },
            { id: "r", header: "What to do", render: (i) => <Runbook slug={i.runbook} title={i.title} /> },
          ]}
        />
      </section>

      <section aria-labelledby="ops-canaries" className="flex flex-col gap-3">
        <h2 id="ops-canaries" className="text-xl font-bold">Canaries</h2>
        <p className="max-w-prose text-fg-muted">Small checks that run on a schedule and prove the important parts still work, before a customer finds out.</p>
        <Table<Canary>
          label="Canaries"
          rows={d.canaries}
          rowKey={(c) => c.key}
          columns={[
            { id: "l", header: "Check", isRowHeader: true, render: (c) => c.label },
            { id: "s", header: "State", render: (c) => CANARY[c.state] },
            { id: "a", header: "Last run", render: (c) => (c.at ? `${formatDate(c.at)}${c.duration_ms != null ? `, ${c.duration_ms} ms` : ""}` : "Never") },
            { id: "d", header: "Result", render: (c) => c.detail || "None yet" },
          ]}
        />
      </section>

      <section aria-labelledby="ops-queues" className="flex flex-col gap-3">
        <h2 id="ops-queues" className="text-xl font-bold">Queues and the last 24 hours</h2>
        <dl className="grid max-w-xl grid-cols-[1fr_max-content] gap-x-6 gap-y-1">
          {Object.entries(d.queues).filter(([q]) => ["system", "web", "docs"].includes(q)).map(([q, n]) => (
            <div key={q} className="contents"><dt>Jobs waiting in the {q} queue</dt><dd className="font-semibold">{n ?? "unknown"}</dd></div>
          ))}
          {Object.entries(d.stats).map(([k, v]) => <div key={k} className="contents"><dt>{STAT_LABEL[k] ?? k}</dt><dd className="font-semibold">{v}</dd></div>)}
        </dl>
      </section>
    </div>
  );
}
