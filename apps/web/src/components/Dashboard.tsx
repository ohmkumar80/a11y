"use client";

import NextLink from "next/link";
import { useEffect, type ReactNode } from "react";
import { DomainsPanel } from "@/components/DomainsPanel";
import { NewScanForm } from "@/components/NewScanForm";
import { ScansTable } from "@/components/ScansTable";
import { Tip } from "@/components/Tip";
import type { User } from "@/lib/api";
import { STATUS_LABEL as SUB_LABEL, daysLeft, type Subscription } from "@/lib/billing";
import { useFlags } from "@/lib/flags";
import { isActive, type ScanRow } from "@/lib/scans";
import { useApi } from "@/lib/useApi";

const STAGES = [
  { title: "Scan", text: "Give us a web address to check." },
  { title: "Read the results", text: "See what was found and how serious it is." },
  { title: "Fix", text: "Work through the problems in the Fix Workbench." },
  { title: "Report", text: "Create a report and have a person sign it off." },
];

interface Step { stage: number; title: string; text: string; href: string; action: string; more?: { href: string; label: string } }

/** Works out where the person is in the audit and what to do next, from their own scans. */
function nextStep(scans: ScanRow[] | null): Step {
  if (!scans || scans.length === 0) {
    return { stage: 0, title: "Run your first scan", text: "Enter a web address to see what people who use assistive technology run into on that page.", href: "#new-scan", action: "Start a scan" };
  }
  const running = scans.find((s) => isActive(s.status));
  if (running) {
    return { stage: 0, title: "Your scan is running", text: "Results appear as soon as it finishes, and you can leave this page meanwhile.", href: `/workspace/scan?id=${running.id}`, action: "Watch progress" };
  }
  const done = scans.find((s) => s.status === "SUCCEEDED");
  if (!done) {
    return { stage: 0, title: "Your last scan did not finish", text: "Open it to see why, then start it again.", href: `/workspace/scan?id=${scans[0]!.id}`, action: "See what happened" };
  }
  const host = (() => { try { return new URL(done.url).host; } catch { return done.url; } })();
  if (done.findings_count > 0) {
    return {
      stage: 2,
      title: "Fix the problems from your latest scan",
      text: `${done.findings_count} ${done.findings_count === 1 ? "issue was" : "issues were"} reported on ${host}. Start with the most serious ones: the Workbench shows where each is on the page and a checked fix.`,
      href: `/workspace/scan/workbench?id=${done.id}`, action: "Open the Fix Workbench",
      more: { href: `/workspace/scan?id=${done.id}`, label: "Read the results first" },
    };
  }
  return {
    stage: 3,
    title: "No automated problems were found",
    text: `Automated tests cannot check everything on ${host}. Before you share a report, have a person review the items only they can judge.`,
    href: `/workspace/scan?id=${done.id}`, action: "Create a report",
  };
}

function Spark({ values }: { values: number[] }) {
  const w = 120, h = 34, max = Math.max(...values, 1);
  const pts = values.map((v, i) => [2 + (i * (w - 4)) / (values.length - 1), h - 3 - (v / max) * (h - 8)] as const);
  const last = pts[pts.length - 1]!;
  return (
    <svg role="img" aria-label={`Issues found in your last ${values.length} finished scans, oldest to newest: ${values.join(", ")}`} viewBox={`0 0 ${w} ${h}`} className="h-9 w-32 text-fg">
      <polyline points={pts.map((p) => p.join(",")).join(" ")} fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="miter" />
      <rect x={last[0] - 3.5} y={last[1] - 3.5} width="7" height="7" className="fill-accent" />
    </svg>
  );
}

function Figure({ label, value, children }: { label: string; value: ReactNode; children?: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1 bg-bg px-4 py-5 sm:px-5">
      <dt className="a11y-kicker">{label}</dt>
      <dd className="font-display text-5xl font-semibold leading-none">{value}</dd>
      {children && <dd className="mt-1 flex flex-col gap-2 text-sm text-fg-muted">{children}</dd>}
    </div>
  );
}

function Metrics({ scans, verified, domainTotal, sub, canVerify }: { scans: ScanRow[] | null; verified: number | null; domainTotal: number | null; sub: Subscription | null; canVerify: boolean }) {
  const done = (scans ?? []).filter((s) => s.status === "SUCCEEDED");
  const latest = done[0];
  const previous = done[1];
  const trend = done.slice(0, 8).reverse().map((s) => s.findings_count);
  const running = (scans ?? []).filter((s) => isActive(s.status)).length;
  const quota = sub?.quotas.find((q) => q.feature === "urls_monthly");
  const pct = quota && quota.limit ? Math.min(100, Math.round((quota.used / quota.limit) * 100)) : 0;

  return (
    <section aria-labelledby="glance-h" className="!border-t-0 !pt-0">
      <h2 id="glance-h" className="a11y-sr-only">At a glance</h2>
      <dl className="grid gap-0.5 border-y-[3px] border-fg bg-fg sm:grid-cols-2 md:grid-cols-[repeat(auto-fit,minmax(11.5rem,1fr))]">
        <Figure label="Scans this month" value={quota ? (quota.limit === null ? quota.used : `${quota.used}/${quota.limit}`) : (scans ? scans.length : "…")}>
          {quota ? (
            <>
              {quota.limit !== null && <span aria-hidden="true" className="block h-2.5 border-2 border-fg bg-bg"><span className="block h-full bg-accent" style={{ width: `${pct}%` }} /></span>}
              <span>{quota.limit === null ? "No monthly limit on your plan." : `${Math.max(0, quota.limit - quota.used)} left this month.`}</span>
            </>
          ) : <span>Recent scans in this list.</span>}
        </Figure>
        <Figure label="Issues in the latest scan" value={latest ? latest.findings_count : "–"}>
          {latest ? (
            <>
              {trend.length > 1 && <Spark values={trend} />}
              <span>
                {previous
                  ? latest.findings_count === previous.findings_count ? "Same as the scan before."
                    : `${Math.abs(latest.findings_count - previous.findings_count)} ${latest.findings_count < previous.findings_count ? "fewer" : "more"} than the scan before.`
                  : "Your first finished scan."}
              </span>
            </>
          ) : <span>Run a scan to see this.</span>}
        </Figure>
        <Figure label="Running now" value={scans ? running : "…"}>
          <span>{running > 0 ? "Results appear here as they arrive." : "Nothing is running."}</span>
        </Figure>
        {canVerify && (
          <Figure label="Verified sites" value={verified === null ? "…" : `${verified}/${domainTotal}`}>
            <span>{verified ? "You can crawl these sites in full." : "Verify a site to scan more than a few pages."}</span>
          </Figure>
        )}
        {sub && (
          <Figure label="Plan" value={<span className="text-4xl">{sub.plan.name}</span>}>
            <span>
              {SUB_LABEL[sub.status]}
              {sub.status === "TRIALING" && sub.trial_ends_at ? `, ${daysLeft(sub.trial_ends_at)} days left` : ""}
              {sub.seats.limit !== null ? `. ${sub.seats.used} of ${sub.seats.limit} seats used.` : ""}
            </span>
            {canVerify && <NextLink href="/org" className="font-bold text-fg underline underline-offset-4 hover:text-accent">Plan and billing</NextLink>}
          </Figure>
        )}
      </dl>
    </section>
  );
}

function DocumentsCard() {
  const flags = useFlags();
  if (!flags.documents) return null;
  return (
    <section aria-labelledby="docs-link" className="flex flex-col gap-3">
      <h2 id="docs-link">Documents</h2>
      <p className="text-fg-muted">Check PDF, Word, PowerPoint and EPUB files, not only web pages.</p>
      <p><NextLink href="/workspace/documents" className="inline-flex min-h-11 items-center border-2 border-fg bg-bg px-4 font-bold shadow-glow transition-[transform,box-shadow] hover:-translate-x-px hover:-translate-y-px hover:bg-bg-inset hover:shadow-lift">Go to your documents</NextLink></p>
    </section>
  );
}

export function Dashboard({ user }: { user: User }) {
  const canVerify = user.role === "COMPANY_ADMIN";
  const scans = useApi<{ total: number; scans: ScanRow[] }>("/scans?limit=25");
  const domains = useApi<Array<{ id: string; verified: boolean }>>(canVerify ? "/domains" : null);
  const sub = useApi<Subscription>("/org/subscription");
  const rows = scans.data?.scans ?? null;

  // Refresh quietly while something is running; nothing here is a live region (no chatter).
  const anyActive = rows?.some((s) => isActive(s.status));
  const reload = scans.reload;
  useEffect(() => {
    if (!anyActive) return;
    const t = setInterval(() => void reload(), 4000);
    return () => clearInterval(t);
  }, [anyActive, reload]);

  const step = nextStep(rows);

  return (
    <div className="a11y-stack flex flex-col gap-12">
      <section aria-labelledby="next-h" className="a11y-ink grid gap-8 border border-inverse-border/60 p-6 sm:p-10 xl:grid-cols-[1.1fr_1fr] xl:items-end">
        <div className="flex flex-col gap-4">
          <p className="a11y-kicker">Your next step</p>
          <h2 id="next-h" className="text-4xl font-semibold sm:text-5xl">{step.title}</h2>
          <p className="max-w-xl text-lg text-inverse-muted">{step.text}</p>
          <p className="flex flex-wrap items-center gap-x-6 gap-y-2 pt-2">
            <NextLink href={step.href} className="inline-flex min-h-12 items-center border-2 border-inverse-fg bg-inverse-fg px-6 text-lg font-bold text-inverse-bg shadow-[4px_4px_0_var(--a11y-inverse-accent)] transition-[transform,box-shadow] hover:-translate-x-px hover:-translate-y-px">{step.action}</NextLink>
            {step.more && <NextLink href={step.more.href} className="inline-flex min-h-11 items-center font-bold text-inverse-fg underline underline-offset-4 hover:text-inverse-accent">{step.more.label}</NextLink>}
          </p>
        </div>
        <ol aria-label="Where you are in an audit" className="grid gap-0">
          {STAGES.map((s, i) => {
            const now = i === step.stage;
            return (
              <li key={s.title} aria-current={now ? "step" : undefined} className={`grid grid-cols-[2.5rem_1fr] gap-x-3 border-t border-inverse-border/60 py-3 ${now ? "bg-white/10 px-3" : i < step.stage ? "text-inverse-muted" : "text-inverse-muted"}`}>
                <span className={`a11y-kicker ${now ? "!text-inverse-accent" : ""}`}>{i < step.stage ? "Done" : `0${i + 1}`}</span>
                <span>
                  <span className={`block font-display text-xl ${now ? "font-bold text-inverse-fg" : "font-semibold"}`}>
                    {s.title}{now && <span className="a11y-sr-only"> (you are here)</span>}
                  </span>
                  <span className="block text-sm">{s.text}</span>
                </span>
              </li>
            );
          })}
        </ol>
      </section>

      <Metrics
        scans={rows}
        verified={domains.data ? domains.data.filter((d) => d.verified).length : null}
        domainTotal={domains.data ? domains.data.length : null}
        sub={sub.data}
        canVerify={canVerify}
      />

      <ScansTable scans={rows} />

      <div className="grid gap-12 xl:grid-cols-2">
        <div className="a11y-stack flex min-w-0 flex-col gap-12">
          <NewScanForm canVerify={canVerify} />
        </div>
        <div className="a11y-stack flex min-w-0 flex-col gap-12">
          {canVerify && <DomainsPanel />}
          <DocumentsCard />
        </div>
      </div>
      {rows && rows.length === 0 && <Tip title="Welcome">Everything you need starts with the form on this page. After your first scan finishes, this page fills with your results, trends and the next thing to do.</Tip>}
    </div>
  );
}
