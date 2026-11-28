"use client";

import { useState } from "react";
import { Button, Dialog, DialogTrigger, StatusMessage, TextField, notify } from "@a11y/ui";
import { post } from "@/lib/api";
import { formatDateTime } from "@/lib/documents";
import { useApi } from "@/lib/useApi";

interface Person { id: string; email: string; role: string; active: boolean; open: number; done_30d: number; mfa: boolean }
interface Overview {
  waiting: number; in_review: number; overdue: number; finished_30d: number; delivered_30d: number; on_time_percent: number | null;
  avg_elapsed_minutes: number; avg_reported_minutes: number; cost_per_hour: number; cost_per_review: number | null; cost_per_page: number | null;
  reviewers: Person[]; in_progress: { id: string; claimed_at: string; due_at: string; reviewer: string }[];
}

const rupees = (n: number) => `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;

/** Reviewers, the review queue's health and what a review costs. Policy (on or off, target hours, limits, the hourly cost)
 *  is the documents.review setting in the Settings tab. */
export function ReviewsTab() {
  const ov = useApi<Overview>("/admin/reviews/overview");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fieldError, setFieldError] = useState<{ field?: string; detail: string } | null>(null);
  const [busy, setBusy] = useState(false);
  if (ov.error) return <StatusMessage>{ov.error.detail}</StatusMessage>;
  if (!ov.data) return <p role="status">Loading the review overview.</p>;
  const d = ov.data;

  async function create() {
    setBusy(true); setFieldError(null);
    const r = await post("/admin/reviewers", { email, password });
    setBusy(false);
    if (r.ok) { notify({ title: "Reviewer created. Pass the password on securely.", kind: "success" }); setEmail(""); setPassword(""); void ov.reload(); }
    else setFieldError({ field: r.problem.field, detail: r.problem.detail });
  }
  async function toggle(p: Person) {
    const r = await post(`/admin/reviewers/${p.id}/active`, { active: !p.active });
    notify(r.ok ? { title: `${p.email} is now ${p.active ? "switched off" : "switched on"}`, kind: "success" } : { title: r.problem.detail, kind: "error" });
    void ov.reload();
  }
  async function takeBack(id: string) {
    const r = await post(`/admin/reviews/${id}/release`);
    notify(r.ok ? { title: "The file is back in the queue", kind: "success" } : { title: r.problem.detail, kind: "error" });
    void ov.reload();
  }

  return (
    <div className="a11y-page-body flex flex-col gap-8">
      <section aria-labelledby="rv-health" className="flex flex-col gap-2">
        <h2 id="rv-health" className="text-xl font-bold">{d.overdue > 0 ? `! ${d.overdue} review${d.overdue === 1 ? " is" : "s are"} overdue` : "✓ No review is overdue"}</h2>
        <dl className="grid max-w-xl grid-cols-[1fr_max-content] gap-x-6 gap-y-1">
          <div className="contents"><dt>Waiting for a reviewer</dt><dd className="font-semibold">{d.waiting}</dd></div>
          <div className="contents"><dt>Being worked on</dt><dd className="font-semibold">{d.in_review}</dd></div>
          <div className="contents"><dt>Finished in the last 30 days</dt><dd className="font-semibold">{d.finished_30d} ({d.delivered_30d} delivered)</dd></div>
          <div className="contents"><dt>Finished within the target time</dt><dd className="font-semibold">{d.on_time_percent === null ? "No reviews yet" : `${d.on_time_percent}%`}</dd></div>
          <div className="contents"><dt>Average time from taking a file to finishing</dt><dd className="font-semibold">{d.avg_elapsed_minutes} minutes</dd></div>
          <div className="contents"><dt>Average time reviewers report</dt><dd className="font-semibold">{d.avg_reported_minutes} minutes</dd></div>
          <div className="contents"><dt>Cost of a review</dt><dd className="font-semibold">{d.cost_per_review === null ? "Set the hourly cost" : rupees(d.cost_per_review)}</dd></div>
          <div className="contents"><dt>Cost per page reviewed</dt><dd className="font-semibold">{d.cost_per_page === null ? "Set the hourly cost" : rupees(d.cost_per_page)}</dd></div>
        </dl>
        <p className="max-w-prose text-fg-muted">Turn reviews on or off, set the target hours, the queue limits and the cost of an hour of reviewer time in the Settings tab, under documents.review. Each can be set for everyone, one plan or one organisation. How many reviews a plan includes is the document_reviews_monthly allowance in the Plans tab. The cost figures use the hourly cost you set; with it at 0 they are hidden.</p>
        <p><Button variant="secondary" onPress={() => void ov.reload()}>Refresh</Button></p>
      </section>

      <section aria-labelledby="rv-progress" className="flex flex-col gap-3">
        <h2 id="rv-progress" className="text-xl font-bold">Files being worked on</h2>
        {d.in_progress.length === 0 ? <p>No file is being worked on.</p> : (
          <ul className="flex max-w-3xl flex-col gap-3">
            {d.in_progress.map((i) => (
              <li key={i.id} className="flex flex-wrap items-center justify-between gap-3 border border-border p-3">
                <span>{i.reviewer} has had it since {formatDateTime(i.claimed_at)} (due {formatDateTime(i.due_at)})</span>
                <Button variant="secondary" onPress={() => void takeBack(i.id)}>Take back<span className="a11y-sr-only"> the file held by {i.reviewer}</span></Button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="rv-people" className="flex flex-col gap-3">
        <h2 id="rv-people" className="text-xl font-bold">Reviewers ({d.reviewers.length})</h2>
        <p className="max-w-prose text-fg-muted">Reviewers are platform staff with no customer account. They sign in on the normal login page, use the same two-step verification policy as administrators, and can open only the files customers asked a person to check.</p>
        {d.reviewers.length === 0 ? <p>There are no reviewers yet. Create one below.</p> : (
          <ul className="flex max-w-3xl flex-col gap-3">
            {d.reviewers.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center justify-between gap-3 border border-border p-3">
                <span>
                  <strong>{p.email}</strong>: {p.active ? "Active" : "Switched off"}
                  <span className="block text-sm text-fg-muted">{p.open} in progress, {p.done_30d} finished in 30 days, two-step verification {p.mfa ? "on" : "not set up yet"}</span>
                </span>
                <span className="flex flex-wrap gap-2">
                  <Button variant="secondary" onPress={() => void toggle(p)}>{p.active ? "Switch off" : "Switch on"}<span className="a11y-sr-only"> {p.email}</span></Button>
                  <PasswordDialog p={p} />
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="rv-new" className="flex max-w-xl flex-col gap-3">
        <h2 id="rv-new" className="text-xl font-bold">Create a reviewer</h2>
        <form className="flex flex-col gap-4" onSubmit={(e) => { e.preventDefault(); void create(); }}>
          <TextField id="field-email" label="Email address" type="email" autoComplete="off" value={email} onChange={setEmail} isRequired error={fieldError?.field === "email" ? fieldError.detail : undefined} />
          <TextField id="field-password" label="First password" type="password" autoComplete="new-password" value={password} onChange={setPassword} isRequired
            description="At least 12 characters. Pass it on securely; they sign in with it and then set up two-step verification." error={fieldError?.field === "password" ? fieldError.detail : undefined} />
          {fieldError && !fieldError.field && <p role="alert" className="font-semibold text-danger">{fieldError.detail}</p>}
          <div><Button type="submit" isPending={busy} pendingLabel="Creating">Create reviewer</Button></div>
        </form>
      </section>
    </div>
  );
}

function PasswordDialog({ p }: { p: Person }) {
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  return (
    <DialogTrigger onOpenChange={(o) => { if (o) { setPw(""); setErr(null); } }}>
      <Button variant="secondary">Set a new password<span className="a11y-sr-only"> for {p.email}</span></Button>
      <Dialog title={`Set a new password for ${p.email}`}>
        {(close) => (
          <form className="flex flex-col gap-4" onSubmit={async (e) => {
            e.preventDefault();
            const r = await post(`/admin/reviewers/${p.id}/password`, { password: pw });
            if (r.ok) { notify({ title: "The password was changed", kind: "success" }); close(); } else setErr(r.problem.detail);
          }}>
            <TextField id={`field-pw-${p.id}`} label="New password" type="password" autoComplete="new-password" value={pw} onChange={setPw} isRequired error={err ?? undefined} />
            <div><Button type="submit">Change the password</Button></div>
          </form>
        )}
      </Dialog>
    </DialogTrigger>
  );
}
