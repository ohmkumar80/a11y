"use client";

import NextLink from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { StatusMessage } from "@a11y/ui";
import { Page } from "@/components/Page";
import { RequireAuth } from "@/components/RequireAuth";
import { ReviewPanel } from "@/components/ReviewPanel";
import { get } from "@/lib/api";
import { auditActive, type AuditDetail, type DocFinding } from "@/lib/documents";
import { formatDate } from "@/lib/billing";
import { SEVERITY_ICON, SEVERITY_LABEL } from "@/lib/scans";

const ORDER = ["critical", "serious", "moderate", "minor"] as const;

function pagesText(f: DocFinding) {
  if (f.pages.length === 0) return null;
  const more = f.pages_total > f.pages.length ? ` and ${f.pages_total - f.pages.length} more` : "";
  return `${f.pages_total === 1 ? "Page" : "Pages"} ${f.pages.join(", ")}${more}`;
}

function Finding({ f }: { f: DocFinding }) {
  return (
    <article aria-labelledby={`f-${f.id}`} className="flex flex-col gap-2 rounded-xl border-2 border-border-subtle p-4">
      <h3 id={`f-${f.id}`} className="text-lg font-bold">
        <span aria-hidden="true">{SEVERITY_ICON[f.severity]} </span>{f.title}
      </h3>
      <p className="text-sm text-fg-muted">
        {SEVERITY_LABEL[f.severity]}
        {f.needs_human ? " · Needs a person to judge or write" : ""}
        {f.count > 1 ? ` · ${f.count} places` : ""}
        {pagesText(f) ? ` · ${pagesText(f)}` : ""}
      </p>
      <p>{f.explanation}</p>
      <p><strong>How to fix it:</strong> {f.how_to_fix}</p>
      {f.wcag.length > 0 && <p className="text-sm">Relates to WCAG {f.wcag.join(", ")}.</p>}
      {f.examples.length > 0 && (
        <details>
          <summary className="cursor-pointer font-semibold">Technical details<span className="a11y-sr-only"> for {f.title}</span></summary>
          <p className="text-sm text-fg-muted">Check {f.rule_id}{f.source === "verapdf" ? " (veraPDF, PDF/UA-1)" : " (our own check)"}.</p>
          <ul className="mt-1 flex flex-col gap-1 text-sm [overflow-wrap:anywhere]">
            {f.examples.map((e, i) => <li key={i}><code>{e.where}</code>{e.message ? `: ${e.message}` : ""}</li>)}
          </ul>
        </details>
      )}
    </article>
  );
}

function Results({ doc, audit }: { doc: string; audit: string }) {
  const [a, setA] = useState<AuditDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [announce, setAnnounce] = useState("");
  const last = useRef("");
  const load = useCallback(async () => {
    const r = await get<AuditDetail>(`/documents/${doc}/audits/${audit}`);
    if (!r.ok) { setError(r.problem.detail); return; }
    setA(r.data);
    if (r.data.status !== last.current) {
      last.current = r.data.status;
      setAnnounce(r.data.status === "SUCCEEDED" ? "The check finished." : r.data.status === "FAILED" ? "The check failed." : "The check is running.");
    }
  }, [doc, audit]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!a || !auditActive(a.status)) return;
    const t = setInterval(() => void load(), 3000);
    return () => clearInterval(t);
  }, [a, load]);

  if (error) return <StatusMessage>{error}</StatusMessage>;
  if (!a) return <p role="status">Loading.</p>;
  const sm = a.summary;
  return (
    <div className="flex flex-col gap-8">
      <p role="status" className="a11y-sr-only">{announce}</p>
      <div>
        <p className="[overflow-wrap:anywhere]"><span className="font-semibold">File:</span> {a.document.filename}</p>
        <p><span className="font-semibold">Checked against:</span> PDF/UA-1, the accessible PDF standard · {a.pages} page{a.pages === 1 ? "" : "s"} · {formatDate(a.created_at)}</p>
      </div>

      {auditActive(a.status) && <p role="status">The check is running. This usually takes under a minute; the page updates by itself.</p>}

      {a.status === "FAILED" && <StatusMessage>{a.error_detail ?? "The check could not be completed."}</StatusMessage>}

      {a.status === "SUCCEEDED" && sm.by_severity && (
        <>
          <section aria-labelledby="summary" className="flex max-w-3xl flex-col gap-3 rounded-xl border-2 border-border-subtle p-4">
            <h2 id="summary" className="text-xl font-bold">
              {sm.verdict === "no_automated_problems" ? "The automated checks found no problems" : `${sm.findings} thing${sm.findings === 1 ? "" : "s"} to fix`}
            </h2>
            {sm.verdict === "problems_found" && (
              <ul className="flex flex-wrap gap-x-6 gap-y-1">
                {ORDER.map((s) => <li key={s}>{SEVERITY_LABEL[s]}: <strong>{sm.by_severity![s]}</strong></li>)}
              </ul>
            )}
            {(sm.needs_a_person ?? 0) > 0 && <p>{sm.needs_a_person} of these need a person: a tool cannot judge what an image shows or whether the reading order makes sense.</p>}
            <p><strong>Not a guarantee.</strong> {sm.caveat}</p>
            {sm.facts && (
              <dl className="grid max-w-md grid-cols-[1fr_max-content] gap-x-6 gap-y-1 text-sm">
                <div className="contents"><dt>Tagged for assistive technology</dt><dd className="font-semibold">{sm.facts.tagged ? "Yes" : "No"}</dd></div>
                <div className="contents"><dt>Document language</dt><dd className="font-semibold">{sm.facts.language ?? "Not set"}</dd></div>
                <div className="contents"><dt>Document title</dt><dd className="font-semibold">{sm.facts.has_title ? "Set" : "Not set"}</dd></div>
                <div className="contents"><dt>Bookmarks</dt><dd className="font-semibold">{sm.facts.has_bookmarks ? "Yes" : "No"}</dd></div>
                <div className="contents"><dt>Pages that are only pictures</dt><dd className="font-semibold">{sm.facts.image_only_pages}</dd></div>
              </dl>
            )}
          </section>

          {ORDER.map((s) => {
            const items = a.findings.filter((f) => f.severity === s);
            if (items.length === 0) return null;
            return (
              <section key={s} aria-labelledby={`sev-${s}`} className="flex max-w-3xl flex-col gap-3">
                <h2 id={`sev-${s}`} className="text-xl font-bold">{SEVERITY_LABEL[s]} ({items.length})</h2>
                {items.map((f) => <Finding key={f.id} f={f} />)}
              </section>
            );
          })}
          {a.document.kind === "pdf" && (sm.facts?.tagged || sm.findings) ? (
            <p className="max-w-3xl"><NextLink href={`/workspace/documents/fix?doc=${a.document.id}`} className="inline-flex min-h-11 items-center font-semibold underline">Fix problems in this document</NextLink>: set the title and language, describe images and correct heading levels in a copy.</p>
          ) : null}
          {a.document.kind === "pdf" && a.status === "SUCCEEDED" && <ReviewPanel docId={a.document.id} />}
          <p className="max-w-3xl">Fixed the file? Upload the new version on the <NextLink href="/workspace/documents" className="underline">documents page</NextLink> and check it again.</p>
        </>
      )}
    </div>
  );
}

function Content() {
  const q = useSearchParams();
  const doc = q.get("doc"), audit = q.get("audit");
  if (!doc || !audit) return <StatusMessage>This page needs a document and a check. Open it from your documents.</StatusMessage>;
  return <Results doc={doc} audit={audit} />;
}

export default function AuditPage() {
  return (
    <RequireAuth>
      {() => (
        <Page title="Document check results" intro="Problems found in your PDF, in plain language, with how to fix each one.">
          <p><NextLink href="/workspace/documents" className="underline">Back to your documents</NextLink></p>
          <Suspense><Content /></Suspense>
        </Page>
      )}
    </RequireAuth>
  );
}
