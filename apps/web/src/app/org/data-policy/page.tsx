"use client";

import NextLink from "next/link";
import { useEffect, useState } from "react";
import { Button, Checkbox, Dialog, DialogTrigger, Select, StatusMessage, TextField } from "@a11y/ui";
import { Page } from "@/components/Page";
import { RequireAuth } from "@/components/RequireAuth";
import { post, put, type Problem } from "@/lib/api";
import type { DataPolicyState } from "@/lib/documents";
import { useApi } from "@/lib/useApi";

const yes = (b: boolean) => (b ? "Yes" : "No");

function Content() {
  const state = useApi<DataPolicyState>("/org/data-policy");
  const [days, setDays] = useState("");
  const [region, setRegion] = useState("default");
  const [review, setReview] = useState(true);
  const [ai, setAi] = useState(false);
  const [zero, setZero] = useState(true);
  const [aiRegions, setAiRegions] = useState<string[]>([]);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const d = state.data;
  useEffect(() => {
    if (!d) return;
    setDays(d.chosen.retention_days ? String(d.chosen.retention_days) : "");
    setRegion(d.chosen.storage_region ?? d.effective.region.id);
    setReview(d.chosen.allow_human_review); setAi(d.chosen.ai_on_documents);
    setZero(d.chosen.ai_require_zero_retention); setAiRegions(d.chosen.ai_regions);
  }, [d]);

  if (state.error) return <StatusMessage>{state.error.detail}</StatusMessage>;
  if (!d) return <p role="status">Loading your data policy.</p>;
  const c = d.controls, e = d.effective;

  async function save() {
    setBusy(true); setProblem(null); setMessage("");
    const r = await put<{ effective: DataPolicyState["effective"]; existing_files_shortened: number }>("/org/data-policy", {
      retention_days: days.trim() === "" ? null : Number(days),
      storage_region: c.can_choose_region ? region : null,
      allow_human_review: review, ai_on_documents: ai, ai_require_zero_retention: zero, ai_regions: aiRegions,
    });
    setBusy(false);
    if (!r.ok) { setProblem(r.problem); return; }
    setMessage(`Saved. ${r.data.existing_files_shortened ? `${r.data.existing_files_shortened} stored file${r.data.existing_files_shortened === 1 ? " now expires" : "s now expire"} sooner. ` : ""}The policy applies from now on.`);
    await state.reload();
  }
  async function deleteAll(close: () => void) {
    const r = await post<{ deleted: number }>("/org/data-policy/delete-documents", { confirm: true });
    close();
    setMessage(r.ok ? `${r.data.deleted} document${r.data.deleted === 1 ? " was" : "s were"} deleted. The files and their encryption keys are gone.` : r.problem.detail);
    await state.reload();
  }
  const err = (f: string) => (problem?.field === f ? problem.detail : undefined);

  return (
    <div className="flex flex-col gap-8">
      <section aria-labelledby="now" className="flex max-w-3xl flex-col gap-2 rounded-xl border-2 border-border-subtle p-4">
        <h2 id="now" className="text-xl font-bold">What is in force now</h2>
        <dl className="grid grid-cols-[1fr_max-content] gap-x-6 gap-y-1">
          <div className="contents"><dt>Files are kept for</dt><dd className="font-semibold">{e.retention_days} days (your plan allows up to {e.retention_ceiling})</dd></div>
          <div className="contents"><dt>New files are stored in</dt><dd className="font-semibold">{e.region.label}</dd></div>
          <div className="contents"><dt>People on our team may open files you ask them to check</dt><dd className="font-semibold">{yes(e.allow_human_review)}</dd></div>
          <div className="contents"><dt>AI models may process your documents</dt><dd className="font-semibold">{yes(e.ai_on_documents)}</dd></div>
          <div className="contents"><dt>Files stored now</dt><dd className="font-semibold">{d.documents.stored}</dd></div>
        </dl>
        <p className="text-sm text-fg-muted">The policy shown is the strictest of what your plan allows and what you chose below. A file stays in the region it was stored in.</p>
      </section>

      <form className="flex max-w-3xl flex-col gap-8" onSubmit={(ev) => { ev.preventDefault(); void save(); }}>
        <fieldset className="flex flex-col gap-3">
          <legend className="text-xl font-bold">How long files are kept</legend>
          <TextField id="field-retention_days" label="Keep files for (days)" type="number" inputMode="numeric" value={days} onChange={setDays} isDisabled={!c.can_set_retention}
            description={c.can_set_retention ? `Leave blank to use your plan's ${e.retention_ceiling} days. You can choose from ${c.min_retention_days} to ${e.retention_ceiling}. A shorter time also applies to files already stored.` : `Your plan keeps files for ${e.retention_ceiling} days. Choosing a shorter time is not part of your plan.`}
            error={err("retention_days")} />
        </fieldset>

        <fieldset className="flex flex-col gap-3">
          <legend className="text-xl font-bold">Where files are stored</legend>
          {c.can_choose_region ? (
            <Select label="Region for new files" value={region} onChange={(k) => setRegion(String(k))} options={d.regions.map((r) => ({ id: r.id, label: r.label }))} error={err("storage_region")} />
          ) : (
            <p>Your files are stored in <strong>{e.region.label}</strong>. Choosing a region is not part of your plan.</p>
          )}
          {d.documents.stored > 0 && <p className="text-sm text-fg-muted">Files already stored stay where they are: {Object.entries(d.documents.by_region).map(([r, n]) => `${n} in ${r}`).join(", ")}.</p>}
        </fieldset>

        <fieldset className="flex flex-col gap-3">
          <legend className="text-xl font-bold">People</legend>
          <Checkbox label="Allow people on the a11y review team to open files I ask them to check" isSelected={review} onChange={setReview} isDisabled={!c.can_block_human_review} />
          <p className="text-sm text-fg-muted">{c.can_block_human_review ? "Turning this off stops anyone on your team asking for a human check. Nobody opens a file unless you ask, and each time is recorded in your audit log." : "Your plan includes human review, and it cannot be switched off. Nobody opens a file unless you ask."}</p>
          {err("allow_human_review") && <p role="alert" className="font-semibold text-danger">{err("allow_human_review")}</p>}
        </fieldset>

        <fieldset className="flex flex-col gap-3">
          <legend className="text-xl font-bold">AI on your documents</legend>
          <p className="text-sm text-fg-muted">AI is off unless you turn it on. Nothing in your documents is sent to an AI provider otherwise.</p>
          <Checkbox label="Allow AI models to process my documents" isSelected={ai} onChange={setAi} isDisabled={!c.can_enable_ai} />
          {!c.can_enable_ai && <p className="text-sm text-fg-muted">Using AI on documents is not part of your plan.</p>}
          {err("ai_on_documents") && <p role="alert" className="font-semibold text-danger">{err("ai_on_documents")}</p>}
          <Checkbox label="Only use providers that do not keep or train on what they receive" isSelected={zero} onChange={setZero} isDisabled={!c.can_enable_ai || !ai} />
          {d.ai_region_options.length > 0 && (
            <fieldset className="flex flex-col gap-1" disabled={!c.can_enable_ai || !ai}>
              <legend className="font-semibold">Only use providers that process in</legend>
              <p className="text-sm text-fg-muted">Choose none to allow any region.</p>
              {d.ai_region_options.map((r) => (
                <Checkbox key={r} label={r.toUpperCase()} isSelected={aiRegions.includes(r)} onChange={(on) => setAiRegions(on ? [...aiRegions, r] : aiRegions.filter((x) => x !== r))} />
              ))}
            </fieldset>
          )}
        </fieldset>

        {problem && !problem.field && <p role="alert" className="font-semibold text-danger">{problem.detail}</p>}
        <div role="status" className="min-h-6">{message}</div>
        <div><Button type="submit" isPending={busy} pendingLabel="Saving">Save the policy</Button></div>
      </form>

      <section aria-labelledby="erase" className="flex max-w-3xl flex-col gap-3 rounded-xl border-2 border-border-subtle p-4">
        <h2 id="erase" className="text-xl font-bold">Delete everything</h2>
        <p>Erase every document and fixed copy you have stored, in every region, now. The files and their encryption keys are removed and the results of their checks go with them. This cannot be undone.</p>
        <DialogTrigger>
          <Button variant="danger" isDisabled={d.documents.stored === 0}>Delete all my documents</Button>
          <Dialog title="Delete all your documents?">
            {(close) => (
              <>
                <p>{d.documents.stored} stored document{d.documents.stored === 1 ? "" : "s"} will be erased now. This cannot be undone.</p>
                <div className="flex gap-3"><Button variant="danger" onPress={() => void deleteAll(close)}>Delete every document</Button></div>
              </>
            )}
          </Dialog>
        </DialogTrigger>
      </section>
    </div>
  );
}

export default function DataPolicyPage() {
  return (
    <RequireAuth requiredRole="COMPANY_ADMIN">
      {() => (
        <Page title="Data policy" intro="Decide how long your documents are kept, where they are stored, who may open them and whether AI may process them.">
          <p><NextLink href="/org" className="underline">Back to your organisation</NextLink></p>
          <Content />
        </Page>
      )}
    </RequireAuth>
  );
}
