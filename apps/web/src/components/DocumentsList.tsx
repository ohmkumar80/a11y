"use client";

import NextLink from "next/link";
import { useEffect, useState } from "react";
import { Button, Dialog, DialogTrigger, StatusMessage } from "@a11y/ui";
import { del, download, post, type Problem } from "@/lib/api";
import { formatDate } from "@/lib/billing";
import { DOC_STATUS, KIND_LABEL, auditActive, formatSize, isWaiting, type DocumentRow } from "@/lib/documents";
import { useApi } from "@/lib/useApi";

function AuditLine({ d }: { d: DocumentRow }) {
  const a = d.latest_audit;
  if (!a) return null;
  const href = `/workspace/documents/audit?doc=${d.id}&audit=${a.id}`;
  if (auditActive(a.status)) return <span className="block text-sm text-fg-muted">Accessibility check in progress.</span>;
  if (a.status === "FAILED") return <span className="block text-sm text-fg-muted">Accessibility check failed. <NextLink href={href} className="underline">See why<span className="a11y-sr-only"> for {d.filename}</span></NextLink></span>;
  const n = a.summary.findings ?? 0;
  return (
    <span className="block text-sm text-fg-muted">
      Accessibility check: {n === 0 ? "no problems found by the automated checks" : `${n} problem${n === 1 ? "" : "s"} found`}.{" "}
      <NextLink href={href} className="underline">View results<span className="a11y-sr-only"> for {d.filename}</span></NextLink>
    </span>
  );
}

/** A native table, not the grid component: the buttons in it must be reachable with the Tab key. */
export function DocumentsList({ refreshKey }: { refreshKey: number }) {
  const { data, error, reload } = useApi<DocumentRow[]>("/documents");
  const [message, setMessage] = useState("");
  const [quota, setQuota] = useState<Problem | null>(null);
  const waiting = data?.some(isWaiting);

  useEffect(() => { void reload(); }, [refreshKey, reload]);
  // Refresh quietly while a file is being checked; the table is not a live region (no chatter).
  useEffect(() => {
    if (!waiting) return;
    const t = setInterval(() => void reload(), 3000);
    return () => clearInterval(t);
  }, [waiting, reload]);

  async function save(d: DocumentRow) {
    const r = await download(`/documents/${d.id}/download`);
    setMessage(r.ok ? `“${d.filename}” was downloaded.` : r.problem.detail);
  }
  async function check(d: DocumentRow) {
    setQuota(null);
    const r = await post(`/documents/${d.id}/audits`);
    if (r.ok) { setMessage(`Checking “${d.filename}” now. The results appear here when it is done.`); void reload(); return; }
    setMessage(r.problem.detail);
    if (r.problem.code === "quota_exceeded" || r.problem.code === "subscription_locked") setQuota(r.problem);
  }
  async function remove(d: DocumentRow, close: () => void) {
    const r = await del(`/documents/${d.id}`);
    close();
    setMessage(r.ok ? `“${d.filename}” was deleted. The file and its encryption key are gone.` : r.problem.detail);
    if (r.ok) void reload();
  }

  return (
    <section aria-labelledby="your-docs" className="flex flex-col gap-3">
      <h2 id="your-docs" className="text-xl font-bold">Your documents</h2>
      <p role="status" className="min-h-6">{message}</p>
      {quota && <p><NextLink href="/org" className="underline">See your plan</NextLink> to check more pages.</p>}
      {error ? <StatusMessage>{error.detail}</StatusMessage> : !data ? <p role="status">Loading your documents.</p> : data.length === 0 ? <p>No documents yet. Upload one above.</p> : (
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- a scrollable region must be focusable so keyboard users can scroll it (axe: scrollable-region-focusable)
        <div role="region" aria-label="Your documents (scrollable)" tabIndex={0} className="relative max-w-full overflow-x-auto rounded-xl border-2 border-border-subtle bg-bg">
          <table className="w-full border-collapse text-left" aria-labelledby="your-docs">
            <thead>
              <tr>
                {["File", "Type and size", "Status", "Added", "Actions"].map((h) => (
                  <th key={h} scope="col" className="min-h-11 border-b-2 border-border-subtle bg-bg-subtle px-4 py-3 text-sm font-semibold">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.map((d) => (
                <tr key={d.id} className="border-b border-border-subtle last:border-b-0">
                  <th scope="row" className="px-4 py-3 font-semibold [overflow-wrap:anywhere]">{d.filename}</th>
                  <td className="px-4 py-3">{KIND_LABEL[d.kind] ?? d.kind}, {formatSize(d.size_bytes)}{d.page_count ? `, ${d.page_count} page${d.page_count === 1 ? "" : "s"}` : ""}</td>
                  <td className="px-4 py-3">
                    {DOC_STATUS[d.status]}
                    {d.reject_detail && <span className="block text-sm text-fg-muted">{d.reject_detail}</span>}
                    {d.latest_audit && <AuditLine d={d} />}
                  </td>
                  <td className="px-4 py-3">{formatDate(d.created_at)}<span className="block text-sm text-fg-muted">Deleted on {formatDate(d.expires_at)}</span></td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-2">
                      {d.ready && d.kind === "pdf" && !auditActive(d.latest_audit?.status) && (
                        <Button variant="secondary" onPress={() => void check(d)}>
                          {d.latest_audit ? "Check again" : "Check accessibility"}<span className="a11y-sr-only"> {d.filename}</span>
                        </Button>
                      )}
                      {d.ready && <Button variant="secondary" onPress={() => void save(d)}>Download<span className="a11y-sr-only"> {d.filename}</span></Button>}
                      <DialogTrigger>
                        <Button variant="secondary">Delete<span className="a11y-sr-only"> {d.filename}</span></Button>
                        <Dialog title={`Delete “${d.filename}”?`}>
                          {(close) => (
                            <>
                              <p>The file is erased now, along with its encryption key. This cannot be undone.</p>
                              <div className="flex gap-3"><Button variant="danger" onPress={() => void remove(d, close)}>Delete file</Button></div>
                            </>
                          )}
                        </Dialog>
                      </DialogTrigger>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
