"use client";

import { useApi } from "@/lib/useApi";

interface Guidance {
  rule: string; review_status: string; summary: string; why: string; who: string[]; steps: string[];
  examples: Array<{ stack: "html" | "react"; before: string; after: string }>;
  links: Array<{ title: string; url: string }>; how_to_check: string; machine_checked: boolean;
}
const STACK: Record<string, string> = { html: "HTML", react: "React (JSX)" };

/** How to fix a finding, in plain language. Shown only when we have written guidance for the rule. */
export function RuleGuidance({ rule }: { rule: string }) {
  const { data, error } = useApi<Guidance>(`/rules/${encodeURIComponent(rule)}/guidance`);
  if (error || !data) return null; // no guidance yet (404) or a failure: the details still work without it
  return (
    <section aria-labelledby="guidance-h" className="mt-4 border-t border-border pt-4">
      <h3 id="guidance-h" className="text-base font-semibold">How to fix this</h3>
      {data.review_status === "draft" && <p className="text-sm">This guidance is awaiting expert review.</p>}
      <p>{data.summary}</p>
      <h4 className="mt-3 font-semibold">Why it matters</h4>
      <p>{data.why}</p>
      <h4 className="mt-3 font-semibold">Who it affects</h4>
      <ul className="list-disc pl-6">{data.who.map((w) => <li key={w}>{w}</li>)}</ul>
      <h4 className="mt-3 font-semibold">Steps</h4>
      <ol className="list-decimal pl-6">{data.steps.map((s) => <li key={s}>{s}</li>)}</ol>
      {data.examples.map((e) => (
        <div key={e.stack} className="mt-3">
          <h4 className="font-semibold">Example in {STACK[e.stack]}</h4>
          <p className="text-sm">Before (fails)</p>
          <pre className="overflow-x-auto rounded border border-border p-2"><code>{e.before}</code></pre>
          <p className="text-sm">After (fixed)</p>
          <pre className="overflow-x-auto rounded border border-border p-2"><code>{e.after}</code></pre>
        </div>
      ))}
      {data.how_to_check && <p className="mt-3"><span className="font-semibold">How to check: </span>{data.how_to_check}</p>}
      {!data.machine_checked && <p className="mt-2 text-sm">A person needs to check this fix: tools cannot tell whether it worked.</p>}
      {data.links.length > 0 && (
        <ul className="mt-3 list-disc pl-6">
          {data.links.map((l) => <li key={l.url}><a href={l.url} className="underline" target="_blank" rel="noreferrer">{l.title}<span className="a11y-sr-only"> (opens in a new tab)</span></a></li>)}
        </ul>
      )}
    </section>
  );
}
