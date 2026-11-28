"use client";

import NextLink from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, StatusMessage } from "@a11y/ui";
import { Page } from "@/components/Page";
import { RequireAuth } from "@/components/RequireAuth";
import { post } from "@/lib/api";
import { formatDateTime, type QueueItem } from "@/lib/documents";
import { useApi } from "@/lib/useApi";

function know(i: QueueItem) {
  const s = i.snapshot;
  const sev = s.by_severity ?? {};
  const parts = [
    `${s.findings ?? 0} problem${s.findings === 1 ? "" : "s"} (${sev.critical ?? 0} critical, ${sev.serious ?? 0} serious)`,
    s.tagged === false ? "not tagged" : "tagged",
    `${s.figures ?? 0} image${s.figures === 1 ? "" : "s"}`,
    `${s.headings ?? 0} heading${s.headings === 1 ? "" : "s"}`,
  ];
  if (s.image_only_pages) parts.push(`${s.image_only_pages} scanned page${s.image_only_pages === 1 ? "" : "s"}`);
  return parts.join(", ");
}

function Due({ i }: { i: QueueItem }) {
  return <>{formatDateTime(i.due_at)}{i.overdue && <strong> · Overdue</strong>}</>;
}

function Queue() {
  const q = useApi<{ items: QueueItem[]; max_claims: number }>("/review/queue");
  const router = useRouter();
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  if (q.error) return <StatusMessage>{q.error.detail}</StatusMessage>;
  if (!q.data) return <p role="status">Loading the queue.</p>;
  const mine = q.data.items.filter((i) => i.mine);
  const waiting = q.data.items.filter((i) => !i.mine);

  async function take(i: QueueItem) {
    setBusy(true); setMessage("");
    const r = await post(`/review/${i.id}/claim`);
    setBusy(false);
    if (r.ok) router.push(`/review/item?id=${i.id}`);
    else { setMessage(r.problem.detail); void q.reload(); }
  }

  return (
    <div className="flex flex-col gap-8">
      <p className="max-w-3xl text-fg-muted">
        Customers asked a person to check these files and agreed to it. You see sizes and counts only. A file&apos;s name, the customer&apos;s note and its content appear once you take it, and each time you open or download it is recorded in the customer&apos;s audit log.
        You can hold up to {q.data.max_claims} files at once.
      </p>
      <div role="status" className="min-h-6">{message}</div>

      <section aria-labelledby="mine" className="flex flex-col gap-3">
        <h2 id="mine" className="text-xl font-bold">Files you are working on ({mine.length})</h2>
        {mine.length === 0 ? <p>You have no files. Take one from the list below.</p> : (
          <ul className="flex max-w-3xl flex-col gap-3">
            {mine.map((i) => (
              <li key={i.id} className="flex flex-wrap items-center justify-between gap-3 border border-border p-3">
                <span>Due by <Due i={i} />, {i.pages} page{i.pages === 1 ? "" : "s"}<span className="block text-sm text-fg-muted">{know(i)}</span></span>
                <NextLink href={`/review/item?id=${i.id}`} className="inline-flex min-h-11 items-center rounded-lg border-2 border-border px-4 font-semibold underline">
                  Open<span className="a11y-sr-only"> the file due {formatDateTime(i.due_at)}</span>
                </NextLink>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="waiting" className="flex flex-col gap-3">
        <h2 id="waiting" className="text-xl font-bold">Waiting for a reviewer ({waiting.length})</h2>
        <p><Button variant="secondary" onPress={() => void q.reload()}>Refresh the queue</Button></p>
        {waiting.length === 0 ? <p>Nothing is waiting.</p> : (
          // A native table, so the buttons in it can be reached with the Tab key.
          // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- a scrollable region must be focusable so keyboard users can scroll it (axe: scrollable-region-focusable)
          <div role="region" aria-label="Waiting for a reviewer (scrollable)" tabIndex={0} className="relative max-w-full overflow-x-auto border border-border bg-bg">
            <table className="w-full border-collapse text-left" aria-labelledby="waiting">
              <thead>
                <tr>{["Due by", "Pages", "What we know", "Action"].map((h) => <th key={h} scope="col" className="border-b-2 border-fg bg-bg-subtle px-4 py-3 text-sm font-semibold">{h}</th>)}</tr>
              </thead>
              <tbody>
                {waiting.map((i) => (
                  <tr key={i.id} className="border-b border-border-subtle last:border-b-0">
                    <th scope="row" className="px-4 py-3 font-semibold"><Due i={i} /></th>
                    <td className="px-4 py-3">{i.pages}</td>
                    <td className="px-4 py-3">{know(i)}</td>
                    <td className="px-4 py-3"><Button isDisabled={busy} onPress={() => void take(i)}>Take this file<span className="a11y-sr-only"> due {formatDateTime(i.due_at)}</span></Button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

export default function ReviewPage() {
  return (
    <RequireAuth requiredRole={["REVIEWER", "SUPER_ADMIN"]}>
      {() => (
        <Page title="Review queue" intro="Documents that customers asked a person to check, oldest deadline first.">
          <Queue />
        </Page>
      )}
    </RequireAuth>
  );
}
