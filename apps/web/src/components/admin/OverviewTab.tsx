"use client";

import NextLink from "next/link";
import type { ReactNode } from "react";
import { Tip } from "@/components/Tip";
import { useApi } from "@/lib/useApi";

interface Tenant { id: string; status: string | null; trial_ends_at: string | null }
interface Funnel { by_status: Record<string, number>; signups_last_30_days: number; trials_ending_within_7_days: number }
interface Ops { status: "ok" | "degraded" | "down"; stats: Record<string, number>; incidents: Array<{ severity: string }> }
interface Reviews { waiting: number; in_review: number; overdue: number; on_time_percent: number | null }
interface Docs { health: { scanner: string; storage: string }; expired_waiting: number }

const SYSTEM = { ok: "Healthy", degraded: "Warnings", down: "Problems" } as const;

function Figure({ label, value, note }: { label: string; value: ReactNode; note: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-1 bg-bg px-4 py-5 sm:px-5">
      <dt className="a11y-kicker">{label}</dt>
      <dd className="font-display text-5xl font-semibold leading-none">{value}</dd>
      <dd className="mt-1 text-sm text-fg-muted">{note}</dd>
    </div>
  );
}

/** One screen that answers "is anything on fire, and what needs me?", with a link to where to act. */
export function OverviewTab() {
  const tenants = useApi<Tenant[]>("/admin/tenants").data;
  const funnel = useApi<Funnel>("/admin/trial-funnel").data;
  const ops = useApi<Ops>("/admin/ops").data;
  const reviews = useApi<Reviews>("/admin/reviews/overview").data;
  const docs = useApi<Docs>("/admin/documents/overview").data;

  const attention: Array<{ text: string; tab: string; action: string }> = [];
  if (ops && ops.status !== "ok") attention.push({ text: ops.status === "down" ? "There are system problems." : "The system is working, with warnings.", tab: "ops", action: "Open Operations" });
  if (reviews && reviews.overdue > 0) attention.push({ text: `${reviews.overdue} ${reviews.overdue === 1 ? "review is" : "reviews are"} overdue.`, tab: "reviews", action: "Open Reviews" });
  if (docs && (docs.health.scanner !== "ok" || docs.health.storage !== "ok")) attention.push({ text: "The document scanner or storage is not responding.", tab: "documents", action: "Open Documents" });
  if (funnel && funnel.trials_ending_within_7_days > 0) attention.push({ text: `${funnel.trials_ending_within_7_days} ${funnel.trials_ending_within_7_days === 1 ? "trial ends" : "trials end"} within a week.`, tab: "tenants", action: "Open Organisations" });

  return (
    <div className="a11y-stack flex flex-col gap-10">
      <section aria-labelledby="glance" className="!border-t-0 !pt-0">
        <h2 id="glance" className="a11y-sr-only">At a glance</h2>
        <dl className="grid gap-0.5 border-y-[3px] border-fg bg-fg sm:grid-cols-2 md:grid-cols-[repeat(auto-fit,minmax(11.5rem,1fr))]">
          <Figure label="Organisations" value={tenants ? tenants.length : "…"} note={funnel ? `${funnel.signups_last_30_days} new in the last 30 days.` : "Loading."} />
          <Figure label="Trials ending soon" value={funnel ? funnel.trials_ending_within_7_days : "…"} note="Within the next 7 days." />
          <Figure label="Reviews waiting" value={reviews ? reviews.waiting : "…"} note={reviews ? `${reviews.in_review} in progress, ${reviews.overdue} overdue.` : "Loading."} />
          <Figure label="Scans in 24 hours" value={ops?.stats.scans_24h ?? "…"} note={ops ? `${ops.stats.scans_succeeded_24h ?? 0} finished successfully.` : "Loading."} />
          <Figure label="System" value={<span className="text-4xl">{ops ? SYSTEM[ops.status] : "…"}</span>} note={ops ? `${ops.incidents.length} open ${ops.incidents.length === 1 ? "incident" : "incidents"}.` : "Loading."} />
        </dl>
      </section>

      <section aria-labelledby="attention">
        <h2 id="attention">Needs your attention</h2>
        {attention.length === 0 ? (
          <p className="mt-3 text-lg">{tenants && ops && reviews ? "Nothing needs attention right now." : "Checking."}</p>
        ) : (
          <ul className="mt-3 border-t border-border">
            {attention.map((a) => (
              <li key={a.text} className="flex flex-wrap items-center justify-between gap-3 border-b border-border py-3">
                <span className="text-lg">{a.text}</span>
                <NextLink href={`/admin?tab=${a.tab}`} className="inline-flex min-h-11 items-center font-bold underline underline-offset-4 hover:text-accent">{a.action}</NextLink>
              </li>
            ))}
          </ul>
        )}
      </section>
      <Tip>Use the navigation on the left to move between admin areas. Every change you make is recorded in the audit log, so you can always see who changed what.</Tip>
    </div>
  );
}
