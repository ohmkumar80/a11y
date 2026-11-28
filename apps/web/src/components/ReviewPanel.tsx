"use client";

import NextLink from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Button, Checkbox, Dialog, DialogTrigger, TextArea } from "@a11y/ui";
import { del, download, get, post, type Problem } from "@/lib/api";
import { formatDateTime, reviewActive, reviewText, type ReviewsInfo } from "@/lib/documents";
import { useFlags } from "@/lib/flags";

/** Asking a person to check a document, with the consent written out, and where that request stands. */
export function ReviewPanel({ docId }: { docId: string }) {
  const flags = useFlags();
  const [info, setInfo] = useState<ReviewsInfo | null>(null);
  const [consent, setConsent] = useState(false);
  const [note, setNote] = useState("");
  const [problem, setProblem] = useState<Problem | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const r = await get<ReviewsInfo>(`/documents/${docId}/reviews`);
    if (r.ok) setInfo(r.data);
  }, [docId]);
  useEffect(() => { void load(); }, [load]);
  const active = reviewActive(info?.reviews[0]?.status);
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => void load(), 5000);
    return () => clearInterval(t);
  }, [active, load]);

  if (!flags.human_review || !info) return null;
  const latest = info.reviews[0];

  async function send(close: () => void) {
    setBusy(true); setProblem(null);
    const r = await post(`/documents/${docId}/reviews`, { note: note.trim() || null, consent });
    setBusy(false);
    if (!r.ok) { setProblem(r.problem); return; }
    close(); setNote(""); setConsent(false);
    setMessage("Your request was sent. A reviewer will take it from the queue.");
    await load();
  }
  async function cancel() {
    if (!latest) return;
    const r = await del(`/documents/${docId}/reviews/${latest.id}`);
    setMessage(r.ok ? "Your request was cancelled and the review was not used." : r.problem.detail);
    await load();
  }

  return (
    <section aria-labelledby="human-review" className="flex max-w-3xl flex-col gap-3 rounded-xl border-2 border-border-subtle p-4">
      <h2 id="human-review" className="text-xl font-bold">Ask a person to check this</h2>
      <p>Some problems need a person: describing a chart, or judging the reading order. A reviewer on our team can look at the file, fix what they can in a copy, and tell you what is left. It uses one review from your plan.</p>
      <div role="status" className="min-h-6">{message}</div>
      {latest && (
        <p><strong>Your request:</strong> {reviewText(latest)}{" "}
          {latest.status === "COMPLETED" && latest.result_document_id && (
            <Button variant="secondary" onPress={() => void download(`/documents/${latest.result_document_id}/download`)}>Download the fixed copy</Button>
          )}
          {latest.status === "REQUESTED" && <Button variant="secondary" onPress={() => void cancel()}>Cancel the request</Button>}
        </p>
      )}
      {latest && <p className="text-sm text-fg-muted">Asked {formatDateTime(latest.requested_at)}.</p>}
      {!reviewActive(latest?.status) && (
        <DialogTrigger onOpenChange={(o) => { if (o) { setProblem(null); setConsent(false); } }}>
          <Button>{latest ? "Ask for another check" : "Ask a person to check this"}</Button>
          <Dialog title="Ask a person to check this document">
            {(close) => (
              <form className="flex flex-col gap-4" onSubmit={(e) => { e.preventDefault(); void send(close); }}>
                <p>{info.consent.text}</p>
                <TextArea label="Anything the reviewer should know (optional)" value={note} onChange={setNote} description="For example, which pages matter most. Do not include passwords or personal details." />
                <Checkbox label="I agree to a person opening this file" isSelected={consent} onChange={setConsent} />
                {problem && (
                  <p role="alert" className="font-semibold text-danger">
                    {problem.detail} {(problem.code === "quota_exceeded" || problem.code === "subscription_locked") && <NextLink href="/org" className="underline">See your plan</NextLink>}
                  </p>
                )}
                <div className="flex gap-3"><Button type="submit" isPending={busy} pendingLabel="Sending" isDisabled={!consent}>Send to a reviewer</Button></div>
              </form>
            )}
          </Dialog>
        </DialogTrigger>
      )}
    </section>
  );
}
