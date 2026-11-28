"use client";

import { useEffect, useRef, useState } from "react";
import { Button, StatusMessage, notify } from "@a11y/ui";
import { get, post } from "@/lib/api";
import { RUNG_LABEL, type Fix } from "@/lib/fixes";

const POLL_MS = 1500;
const GIVE_UP_MS = 120_000;

/** Ask for a code fix for one finding. Only a fix that passed our scanner's own re-check is ever shown as code.
 *  Progress is announced once per milestone, not on every poll. */
export function FixSuggestion({ scanId, findingId }: { scanId: string; findingId: string }) {
  const [fix, setFix] = useState<Fix | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [announce, setAnnounce] = useState("");
  const started = useRef(0);
  const active = fix?.status === "PENDING" || fix?.status === "RUNNING";

  useEffect(() => {
    if (!fix || !active) return;
    const t = setInterval(async () => {
      if (Date.now() - started.current > GIVE_UP_MS) {
        clearInterval(t);
        setError("This is taking longer than expected. Close this window and try again in a few minutes.");
        return;
      }
      const r = await get<Fix>(`/fixes/${fix.id}`);
      if (r.ok && r.data.status !== fix.status) {
        setFix(r.data);
        if (r.data.status === "READY") setAnnounce("A checked fix is ready.");
        else if (r.data.status === "NEEDS_REVIEW") setAnnounce("We could not produce a fix we trust. See the explanation below.");
        else if (r.data.status === "FAILED") setAnnounce("We could not check a fix right now.");
      }
    }, POLL_MS);
    return () => clearInterval(t);
  }, [fix, active]);

  async function ask(retry: boolean) {
    setStarting(true);
    setError(null);
    setAnnounce("Checking a fix. This usually takes a few seconds.");
    started.current = Date.now();
    const r = await post<Fix>(`/scans/${scanId}/findings/${findingId}/fix`, { retry });
    setStarting(false);
    if (!r.ok) { setError(r.problem.detail); setAnnounce(""); return; }
    setFix(r.data);
    if (r.data.status === "READY") setAnnounce("A checked fix is ready.");
  }

  return (
    <section aria-labelledby={`fix-h-${findingId}`} className="mt-4 border-t border-border pt-4">
      <h3 id={`fix-h-${findingId}`} className="text-base font-semibold">Suggested code fix</h3>
      <div role="status" className="min-h-6 text-sm">{announce}</div>
      {error && <StatusMessage>{error}</StatusMessage>}
      {!fix && (
        <>
          <p className="text-sm">
            We try a ready-made fix first. If there is none, an AI model may propose one, which sends only this element&apos;s tag (not the page&apos;s text) to our AI provider.
            Either way, we run our scanner on the result and show it only if the problem is gone and nothing new appears. A ready-made fix is free; a fix written by an AI model uses one of your AI code fixes for the month, and only if we accept it.
          </p>
          <Button variant="secondary" isPending={starting} pendingLabel="Checking a fix" onPress={() => void ask(false)}>Suggest a fix</Button>
        </>
      )}
      {fix && active && <p>Checking a fix with our scanner…</p>}
      {fix?.status === "READY" && fix.fixed_html !== null && <Ready fix={fix} />}
      {fix && (fix.status === "NEEDS_REVIEW" || fix.status === "FAILED") && (
        <div>
          <p>{fix.detail ?? "We could not produce a fix."}</p>
          <Button variant="secondary" isPending={starting} pendingLabel="Checking a fix" onPress={() => void ask(true)}>Try again</Button>
        </div>
      )}
    </section>
  );
}

function Ready({ fix }: { fix: Fix }) {
  const code = fix.fixed_html ?? "";
  return (
    <div>
      <p>{fix.explanation}</p>
      <p className="text-sm">{RUNG_LABEL[fix.rung ?? ""] ?? "Suggested fix"}{fix.from_cache ? " (reused from an identical element)" : ""}.</p>
      {fix.credit_used && <p className="text-sm">This used one of your AI code fixes for the month.</p>}
      <p className="mt-2 text-sm font-semibold">Before</p>
      <pre className="overflow-x-auto rounded-xl border-2 border-border-subtle bg-bg-inset p-3"><code>{fix.original_html}</code></pre>
      <p className="mt-2 text-sm font-semibold">After</p>
      <pre className="overflow-x-auto rounded-xl border-2 border-border-subtle bg-bg-inset p-3"><code>{code === "" ? "(remove this tag)" : code}</code></pre>
      {code !== "" && (
        <Button variant="secondary" onPress={async () => { await navigator.clipboard?.writeText(code); notify({ title: "Fix copied", kind: "success" }); }}>
          Copy fix
        </Button>
      )}
      {fix.notes.length > 0 && (
        <>
          <p className="mt-2 text-sm font-semibold">Check before you use it</p>
          <ul className="list-disc pl-6">{fix.notes.map((n) => <li key={n}>{n}</li>)}</ul>
        </>
      )}
      <p className="mt-2 text-sm font-semibold">What we checked</p>
      <ul className="list-disc pl-6">
        {fix.checks.map((c) => <li key={c.name}><span aria-hidden="true">{c.passed ? "✓" : "✗"}</span> <span className="a11y-sr-only">{c.passed ? "Passed: " : "Failed: "}</span>{c.name}</li>)}
      </ul>
      <p className="text-sm">These checks do not prove the page is accessible. Test the change with a keyboard and a screen reader.</p>
    </div>
  );
}
