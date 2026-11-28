"use client";

import NextLink from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { Button, Select, StatusMessage } from "@a11y/ui";
import { FixSuggestion } from "@/components/FixSuggestion";
import { Page } from "@/components/Page";
import { PageShot } from "@/components/PageShot";
import { RequireAuth } from "@/components/RequireAuth";
import { RuleGuidance } from "@/components/RuleGuidance";
import { get } from "@/lib/api";
import { CONFIDENCE_LABEL, KIND_LABEL, SEVERITY_ICON, SEVERITY_LABEL, type Finding, type Kind, type ScanDetail, type Severity } from "@/lib/scans";

const BATCH = 100;
const SEVERITIES: Severity[] = ["critical", "serious", "moderate", "minor"];
const KINDS: Kind[] = ["violation", "needs_review"];

function Workbench({ id }: { id: string }) {
  const [scan, setScan] = useState<ScanDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState<Kind>("violation");
  const [severity, setSeverity] = useState("all");
  const [items, setItems] = useState<Finding[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [current, setCurrent] = useState<string | null>(null);
  const [whole, setWhole] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const buttons = useRef<Record<string, HTMLButtonElement | null>>({});

  useEffect(() => { void get<ScanDetail>(`/scans/${id}`).then((r) => (r.ok ? setScan(r.data) : setError(r.problem.detail))); }, [id]);

  const fetchPage = useCallback(async (offset: number) => {
    const q = new URLSearchParams({ kind, limit: String(BATCH), offset: String(offset) });
    if (severity !== "all") q.set("severity", severity);
    const r = await get<{ total: number; findings: Finding[] }>(`/scans/${id}/findings?${q}`);
    if (!r.ok) { setError(r.problem.detail); return; }
    setTotal(r.data.total);
    setItems((prev) => (offset === 0 ? r.data.findings : [...prev, ...r.data.findings]));
  }, [id, kind, severity]);

  const done = scan?.status === "SUCCEEDED";
  useEffect(() => { if (done) { setCurrent(null); setItems([]); setTotal(null); void fetchPage(0); } }, [done, fetchPage]);

  const index = items.findIndex((f) => f.id === current);
  const f = index >= 0 ? items[index] : null;
  const pageInfo = f && scan ? scan.pages.find((p) => p.id === f.page.id) : undefined;

  function select(next: Finding) {
    setCurrent(next.id);
    setWhole(false);
    // Move focus to the details so a keyboard or screen reader user lands on what they chose, at any screen width.
    requestAnimationFrame(() => heading.current?.focus());
  }
  function step(delta: number) {
    const n = items[index + delta];
    if (n) select(n);
  }

  if (error) return <StatusMessage>{error}</StatusMessage>;
  if (!scan) return <p>Loading the scan.</p>;
  if (!done) return <StatusMessage>This scan has not finished, so there is nothing to fix yet. <NextLink href={`/workspace/scan?id=${id}`} className="underline">Back to the scan</NextLink>.</StatusMessage>;

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 rounded-2xl border-2 border-border-subtle bg-bg-subtle p-4 sm:grid-cols-[repeat(2,minmax(0,16rem))]">
        <Select label="Show" value={kind} onChange={(k) => setKind(String(k) as Kind)} options={KINDS.map((k) => ({ id: k, label: KIND_LABEL[k] }))} />
        <Select label="Severity" value={severity} onChange={(k) => setSeverity(String(k))} options={[{ id: "all", label: "All" }, ...SEVERITIES.map((s) => ({ id: s, label: SEVERITY_LABEL[s] }))]} />
      </div>
      <p role="status">{total === null ? "Loading problems." : `${total} ${total === 1 ? "problem" : "problems"}${items.length < total ? `, showing ${items.length}` : ""}.`}</p>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        <nav aria-label="Problems to fix" className="flex flex-col gap-2 self-start rounded-2xl border-2 border-border-subtle bg-bg-subtle p-3">
          {total === 0 && <p>Nothing to fix here.</p>}
          <ul className="flex max-h-[32rem] flex-col gap-1 overflow-auto lg:max-h-[75vh]">
            {items.map((x, i) => (
              <li key={x.id}>
                <button
                  type="button"
                  ref={(el) => { buttons.current[x.id] = el; }}
                  aria-current={x.id === current ? "true" : undefined}
                  onClick={() => select(x)}
                  className={`w-full rounded-xl border-2 px-3 py-2 text-left transition-colors ${x.id === current ? "border-accent bg-accent-subtle font-semibold" : "border-border-subtle bg-bg hover:border-border"}`}
                >
                  <span className="block">{SEVERITY_ICON[x.severity]} {SEVERITY_LABEL[x.severity]}: {x.title}</span>
                  <span className="a11y-sr-only">, problem {i + 1} of {total}.</span>
                  <span className="block text-sm text-fg-muted [overflow-wrap:anywhere]">{x.element.tag} on {new URL(x.page.url).pathname || "/"}</span>
                </button>
              </li>
            ))}
          </ul>
          {total !== null && items.length < total && <Button variant="secondary" onPress={() => void fetchPage(items.length)}>Show more problems</Button>}
        </nav>

        <section aria-labelledby="wb-h" className="min-w-0 rounded-2xl border-2 border-border-subtle bg-bg-subtle p-5 sm:p-6">
          {!f ? (
            <>
              <h2 id="wb-h" className="text-xl font-bold">Choose a problem</h2>
              <p>Pick one from the list to see where it is on the page, why it matters and a checked code fix.</p>
            </>
          ) : (
            <div className="flex flex-col gap-3">
              <h2 id="wb-h" ref={heading} tabIndex={-1} className="text-xl font-bold">{f.title}</h2>
              <p className="text-sm">Problem {index + 1} of {total}.</p>
              <div className="flex flex-wrap gap-2">
                <Button variant="secondary" isDisabled={index <= 0} onPress={() => step(-1)}>Previous problem</Button>
                <Button variant="secondary" isDisabled={index >= items.length - 1} onPress={() => step(1)}>Next problem</Button>
                <Button variant="secondary" onPress={() => buttons.current[f.id]?.focus()}>Back to the list</Button>
              </div>
              <dl className="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-1">
                <dt className="font-semibold">Type</dt><dd>{KIND_LABEL[f.kind]}, {SEVERITY_LABEL[f.severity].toLowerCase()}</dd>
                <dt className="font-semibold">Criteria</dt><dd>{f.criteria.length ? f.criteria.map((c) => `${c.clause} ${c.name} (level ${c.level})`).join("; ") : "Best practice (not a WCAG requirement)"}</dd>
                <dt className="font-semibold">Confidence</dt><dd>{CONFIDENCE_LABEL[f.confidence]}</dd>
                <dt className="font-semibold">Page</dt><dd className="[overflow-wrap:anywhere]">{f.page.url}</dd>
                <dt className="font-semibold">Element</dt><dd><code className="[overflow-wrap:anywhere]">{f.element.css}</code></dd>
              </dl>
              {f.message && <p>{f.message}</p>}

              <section aria-labelledby="wb-where" className="flex flex-col gap-2">
                <h3 id="wb-where" className="text-base font-semibold">Where it is</h3>
                {pageInfo?.screenshot ? (
                  <>
                    <PageShot key={`${f.id}-${whole}`} scanId={id} pageId={f.page.id} pageUrl={f.page.url} shot={pageInfo.screenshot} rect={f.element.rect} whole={whole} />
                    <div><Button variant="secondary" onPress={() => setWhole((w) => !w)}>{whole ? "Zoom in on the problem" : "Show the whole saved page"}</Button></div>
                  </>
                ) : (
                  <p>No screenshot was saved for this page. The element&apos;s HTML below shows what is wrong.</p>
                )}
                <p className="font-semibold">HTML of the element</p>
                <pre className="overflow-x-auto rounded-xl border-2 border-border-subtle bg-bg-inset p-3"><code>{f.element.html}</code></pre>
              </section>

              <RuleGuidance key={`g-${f.id}`} rule={f.rule} />
              {f.kind !== "best_practice" && <FixSuggestion key={`f-${f.id}`} scanId={id} findingId={f.id} />}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function Content() {
  const id = useSearchParams().get("id");
  return id ? <Workbench id={id} /> : <StatusMessage>No scan was chosen. <NextLink href="/workspace" className="underline">Go to your scans</NextLink>.</StatusMessage>;
}

export default function WorkbenchPage() {
  return (
    <RequireAuth>
      {() => (
        <Page title="Fix Workbench" intro="Work through the problems one at a time: see where each one is on the page, why it matters and a checked code fix.">
          <p><NextLink href="/workspace" className="underline">Back to your scans</NextLink></p>
          <Suspense><Content /></Suspense>
        </Page>
      )}
    </RequireAuth>
  );
}
