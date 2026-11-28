"use client";

import NextLink from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { Button, StatusMessage, TextArea, TextField } from "@a11y/ui";
import { FixEditor } from "@/components/FixEditor";
import { Page } from "@/components/Page";
import { RequireAuth } from "@/components/RequireAuth";
import { download, get, post, type Problem, type Result } from "@/lib/api";
import { formatDateTime, type FixState, type ReviewDetail } from "@/lib/documents";
import { SEVERITY_LABEL } from "@/lib/scans";

const ORDER = ["critical", "serious", "moderate", "minor"] as const;

function Work({ id }: { id: string }) {
  const router = useRouter();
  const [detail, setDetail] = useState<ReviewDetail | null>(null);
  const [error, setError] = useState<Problem | null>(null);
  const [fixStatus, setFixStatus] = useState<string | undefined>();
  const [outcome, setOutcome] = useState<"deliver" | "decline">("deliver");
  const [message, setMessage] = useState("");
  const [minutes, setMinutes] = useState("");
  const [problem, setProblem] = useState<Problem | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  // The editor and this page read the same endpoint; the editor asks again while a build runs.
  const load = useCallback(async (): Promise<Result<FixState>> => {
    const r = await get<ReviewDetail>(`/review/${id}`);
    if (!r.ok) { setError(r.problem); return r; }
    setDetail(r.data);
    return { ok: true, data: { document: r.data.document, audit_id: r.data.audit.id, structure: r.data.structure, fix: r.data.fix } };
  }, [id]);
  useEffect(() => { void load(); }, [load]);

  if (error) return <StatusMessage>{error.detail} <NextLink href="/review" className="underline">Back to the queue</NextLink></StatusMessage>;
  if (!detail) return <p role="status">Loading the file.</p>;
  const { review, document: doc, findings } = detail;

  async function release() {
    const r = await post(`/review/${id}/release`);
    if (r.ok) router.push("/review"); else setProblem(r.problem);
  }
  async function submit() {
    setBusy(true); setProblem(null);
    const r = await post(`/review/${id}/submit`, { outcome, message: message.trim() || null, minutes: minutes.trim() === "" ? null : Number(minutes) });
    setBusy(false);
    if (r.ok) { setNote(outcome === "deliver" ? "Delivered. The customer has been told." : "Declined. The customer has been told why."); router.push("/review"); }
    else setProblem(r.problem);
  }

  return (
    <div className="flex flex-col gap-8">
      <section aria-labelledby="file" className="flex max-w-3xl flex-col gap-2 border border-border p-4">
        <h2 id="file" className="text-xl font-bold">The file</h2>
        <p className="[overflow-wrap:anywhere]"><span className="font-semibold">Name:</span> {doc.filename} · {doc.page_count ?? "?"} page{doc.page_count === 1 ? "" : "s"}</p>
        <p><span className="font-semibold">Due by:</span> {formatDateTime(review.due_at)} · you took it {formatDateTime(review.claimed_at)}</p>
        <p><span className="font-semibold">The customer&apos;s note:</span> {review.note ?? "None."}</p>
        <div className="flex flex-wrap gap-3">
          <Button variant="secondary" onPress={() => void download(`/review/${id}/original`)}>Download the original</Button>
          <Button variant="secondary" onPress={() => void release()}>Put it back in the queue</Button>
        </div>
      </section>

      <section aria-labelledby="found" className="flex max-w-3xl flex-col gap-2">
        <h2 id="found" className="text-xl font-bold">What the automated check found ({findings.length})</h2>
        {findings.length === 0 ? <p>No problems were found by the automated checks. Judge the alternative text and reading order yourself.</p> : (
          <ul className="flex flex-col gap-2">
            {ORDER.flatMap((s) => findings.filter((f) => f.severity === s)).map((f) => (
              <li key={f.id}><strong>{SEVERITY_LABEL[f.severity]}:</strong> {f.title}{f.needs_human ? " (needs a person)" : ""}{f.pages.length ? `, page ${f.pages.slice(0, 5).join(", ")}${f.pages_total > 5 ? "…" : ""}` : ""}</li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="fix" className="flex flex-col gap-3">
        <h2 id="fix" className="text-xl font-bold">Fix it</h2>
        <FixEditor
          variant="reviewer"
          base={`/review/${id}/fix`}
          load={load}
          onState={(s) => setFixStatus(s.fix?.status)}
          downloadCopy={() => void download(`/review/${id}/result`)}
        />
      </section>

      <section aria-labelledby="finish" className="flex max-w-3xl flex-col gap-4 border border-border p-4">
        <h2 id="finish" className="text-xl font-bold">Finish the review</h2>
        <form className="flex flex-col gap-4" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
          <fieldset className="flex flex-col gap-2">
            <legend className="font-semibold">What happened</legend>
            <label className="flex min-h-11 items-center gap-2"><input type="radio" name="outcome" checked={outcome === "deliver"} onChange={() => setOutcome("deliver")} className="size-5" /> Deliver the fixed copy{fixStatus === "READY" ? "" : " (build it first)"}</label>
            <label className="flex min-h-11 items-center gap-2"><input type="radio" name="outcome" checked={outcome === "decline"} onChange={() => setOutcome("decline")} className="size-5" /> I could not improve this file</label>
          </fieldset>
          <TextArea label={outcome === "decline" ? "Tell the customer why" : "A message for the customer (optional)"} value={message} onChange={setMessage}
            description={outcome === "decline" ? "Required. Say what stopped you and what they could do instead." : "For example, what is still for them to check."} isRequired={outcome === "decline"} />
          <TextField id="field-minutes" label="Minutes you spent (optional)" type="number" inputMode="numeric" value={minutes} onChange={setMinutes} description="Leave blank to use the time since you took the file." />
          {problem && <p role="alert" className="font-semibold text-danger">{problem.detail}</p>}
          <div className="flex gap-3">
            <Button type="submit" isPending={busy} pendingLabel="Sending" isDisabled={outcome === "deliver" && fixStatus !== "READY"}>{outcome === "deliver" ? "Deliver to the customer" : "Decline with this reason"}</Button>
          </div>
          <p role="status" className="min-h-6">{note}</p>
        </form>
      </section>
    </div>
  );
}

function Content() {
  const id = useSearchParams().get("id");
  if (!id) return <StatusMessage>This page needs a review. Open one from the queue.</StatusMessage>;
  return <Work id={id} />;
}

export default function ReviewItemPage() {
  return (
    <RequireAuth requiredRole={["REVIEWER", "SUPER_ADMIN"]}>
      {() => (
        <Page title="Review a document" intro="Fix what you can in a copy with the same tools the customer has, then deliver it or explain why you could not.">
          <p><NextLink href="/review" className="underline">Back to the queue</NextLink></p>
          <Suspense><Content /></Suspense>
        </Page>
      )}
    </RequireAuth>
  );
}
