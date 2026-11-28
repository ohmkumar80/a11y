"use client";

import NextLink from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { Button, Select, StatusMessage, TextArea, TextField } from "@a11y/ui";
import { Page } from "@/components/Page";
import { RequireAuth } from "@/components/RequireAuth";
import { download, get, post, put, type Problem } from "@/lib/api";
import { LANGUAGES, fixActive, type FixPlan, type FixState } from "@/lib/documents";
import { SEVERITY_LABEL } from "@/lib/scans";

const LEVELS = [1, 2, 3, 4, 5, 6].map((n) => ({ id: String(n), label: `Level ${n}` }));
const SEV = ["critical", "serious", "moderate", "minor"] as const;

function Counts({ by }: { by: Record<string, number> }) {
  return <>{SEV.map((s) => `${SEVERITY_LABEL[s]}: ${by[s] ?? 0}`).join(", ")}</>;
}

function Editor({ doc }: { doc: string }) {
  const [state, setState] = useState<FixState | null>(null);
  const [error, setError] = useState<Problem | null>(null);
  const [title, setTitle] = useState("");
  const [lang, setLang] = useState("keep");
  const [otherLang, setOtherLang] = useState("");
  const [alt, setAlt] = useState<Record<string, string>>({});
  const [levels, setLevels] = useState<Record<string, number>>({});
  const [message, setMessage] = useState("");
  const [problem, setProblem] = useState<Problem | null>(null);
  const [busy, setBusy] = useState(false);
  const loaded = useRef(false);

  const load = useCallback(async () => {
    const r = await get<FixState>(`/documents/${doc}/fix`);
    if (!r.ok) { setError(r.problem); return; }
    setState(r.data);
    if (!loaded.current) { // fill the form once, from a saved draft if there is one
      loaded.current = true;
      const p = r.data.fix?.status === "DRAFT" ? r.data.fix.plan : {};
      setTitle(p.title ?? ""); setAlt(p.alt ?? {}); setLevels(p.heading_levels ?? {});
      const known = LANGUAGES.some((l) => l.id === p.language);
      setLang(p.language ? (known ? p.language : "__other") : "keep"); setOtherLang(known ? "" : (p.language ?? ""));
    }
  }, [doc]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!fixActive(state?.fix?.status)) return;
    const t = setInterval(() => void load(), 3000);
    return () => clearInterval(t);
  }, [state, load]);

  if (error) return <StatusMessage>{error.detail} {error.code === "needs_audit" && <NextLink href="/workspace/documents" className="underline">Go to your documents</NextLink>}</StatusMessage>;
  if (!state) return <p role="status">Loading.</p>;
  const st = state.structure;
  const fix = state.fix;
  const building = fixActive(fix?.status);
  const done = fix?.status === "READY";

  function plan(): FixPlan {
    const language = lang === "__other" ? otherLang.trim() : lang === "keep" ? "" : lang;
    return {
      title: title.trim() || undefined,
      language: language || undefined,
      alt: Object.fromEntries(Object.entries(alt).filter(([, v]) => v.trim() !== "")),
      heading_levels: Object.fromEntries(st.headings.filter((h) => h.id && levels[h.id] && levels[h.id] !== h.level).map((h) => [h.id as string, levels[h.id as string] as number])),
    };
  }

  async function save(): Promise<boolean> {
    setProblem(null);
    const r = await put(`/documents/${doc}/fix`, plan());
    if (!r.ok) { setProblem(r.problem); return false; }
    return true;
  }
  async function onSave() {
    setBusy(true);
    if (await save()) setMessage("Your changes are saved. Nothing has been changed in the file yet.");
    setBusy(false);
  }
  async function onBuild() {
    setBusy(true); setMessage("");
    if (await save()) {
      const r = await post(`/documents/${doc}/fix/build`);
      if (r.ok) { setMessage("Building the fixed copy. This usually takes under a minute, and the page updates by itself."); await load(); }
      else setProblem(r.problem);
    }
    setBusy(false);
  }

  return (
    <div className="flex flex-col gap-8">
      <p className="max-w-3xl">
        Changes are made to a <strong>copy</strong> of <span className="[overflow-wrap:anywhere]">{state.document.filename}</span>. The original is never changed.
        Building the copy checks it again and uses {state.document.page_count ?? 1} of your document pages.
      </p>
      <p className="max-w-3xl text-fg-muted">You can describe images and change heading levels because this file has tags. Page previews are not available yet: to find an image, open the original and look at the page shown.</p>

      {(building || done || fix?.status === "FAILED") && (
        <section aria-labelledby="result" className="flex max-w-3xl flex-col gap-3 rounded-xl border-2 border-border-subtle p-4">
          <h2 id="result" className="text-xl font-bold">{building ? "Building your fixed copy" : done ? "Your fixed copy is ready" : "The fixed copy could not be made"}</h2>
          {building && <p role="status">Working on it.</p>}
          {fix?.status === "FAILED" && <p>{fix.error_detail}</p>}
          {done && fix.result.before && fix.result.after && (
            <>
              <p>Before: {fix.result.before.findings} problem{fix.result.before.findings === 1 ? "" : "s"} (<Counts by={fix.result.before.by_severity} />).</p>
              <p>After: {fix.result.after.findings} problem{fix.result.after.findings === 1 ? "" : "s"} (<Counts by={fix.result.after.by_severity} />).</p>
              {(fix.result.resolved ?? []).length > 0 && (
                <div><h3 className="font-semibold">Fixed</h3><ul className="list-disc pl-6">{fix.result.resolved!.map((r) => <li key={r.rule_id}>{r.title}</li>)}</ul></div>
              )}
              {(fix.result.remaining ?? []).length > 0 && (
                <div><h3 className="font-semibold">Still to do</h3><ul className="list-disc pl-6">{fix.result.remaining!.map((r) => <li key={r.rule_id}>{SEVERITY_LABEL[r.severity]}: {r.title}</li>)}</ul></div>
              )}
              <p><strong>Not a guarantee.</strong> A person still needs to check that the alternative text is meaningful and the reading order makes sense.</p>
              <div className="flex flex-wrap gap-3">
                <Button onPress={() => void download(`/documents/${fix.result_document_id}/download`)}>Download the fixed copy</Button>
                <NextLink href="/workspace/documents" className="inline-flex min-h-11 items-center underline">Back to your documents</NextLink>
              </div>
            </>
          )}
        </section>
      )}

      <div role="status" className="min-h-6">{message}</div>
      {problem && (
        <p role="alert" className="font-semibold text-danger">
          {problem.detail} {(problem.code === "quota_exceeded" || problem.code === "subscription_locked") && <NextLink href="/org" className="underline">See your plan</NextLink>}
        </p>
      )}

      <form className="flex max-w-3xl flex-col gap-8" onSubmit={(e) => { e.preventDefault(); void onBuild(); }}>
        <fieldset className="flex flex-col gap-3" disabled={building}>
          <legend className="text-xl font-bold">Document properties</legend>
          <TextField id="field-title" label="Title" value={title} onChange={setTitle} description={st.title ? `Now: ${st.title}` : "Not set. A screen reader announces the title when the file opens."} />
          <Select label="Language" value={lang} onChange={(k) => setLang(String(k ?? "keep"))} options={LANGUAGES} />
          {lang === "__other" && <TextField id="field-language" label="Language code" value={otherLang} onChange={setOtherLang} description="For example fr-CA or pa." />}
          <p className="text-sm text-fg-muted">{st.language ? `The file currently says it is in: ${st.language}.` : "The file does not say what language it is in."}</p>
        </fieldset>

        {!st.has_structure && (
          <StatusMessage>This file has no tags, so image descriptions and heading levels cannot be changed here. Re-export it from the original document with tagging switched on, or use a PDF accessibility tool.</StatusMessage>
        )}

        {st.has_structure && (
          <fieldset className="flex flex-col gap-4" disabled={building}>
            <legend className="text-xl font-bold">Images ({st.figures.length})</legend>
            {st.figures.length === 0 && <p>No images are tagged in this file.</p>}
            {st.figures.map((f, i) => f.editable && f.id && (
              <TextArea key={f.id} label={`Alternative text for image ${i + 1}${f.page ? `, on page ${f.page}` : ""}`} value={alt[f.id] ?? ""}
                onChange={(v) => setAlt({ ...alt, [f.id as string]: v })}
                description={`${f.alt ? `Now: “${f.alt}”. ` : "No description yet. "}Say what the image shows or what it is for, in a short sentence. Leave blank to keep as it is.`} />
            ))}
          </fieldset>
        )}

        {st.has_structure && (
          <fieldset className="flex flex-col gap-4" disabled={building}>
            <legend className="text-xl font-bold">Headings ({st.headings.length})</legend>
            <p className="text-sm text-fg-muted">Headings should go in order: level 1, then 2, then 3, without skipping. Change the level here; the text and layout stay as they are.</p>
            {st.headings.length === 0 && <p>No headings are tagged in this file.</p>}
            {st.headings.map((h) => h.id && h.editable && (
              <Select key={h.id} label={`Level of the heading “${h.text || "text not available"}”${h.page ? `, page ${h.page}` : ""}`}
                value={String(levels[h.id] ?? h.level)} onChange={(k) => setLevels({ ...levels, [h.id as string]: Number(k) })} options={LEVELS} />
            ))}
          </fieldset>
        )}

        <div className="flex flex-wrap gap-3">
          <Button type="submit" isPending={busy} pendingLabel="Working" isDisabled={building}>Build the fixed copy</Button>
          <Button variant="secondary" isDisabled={busy || building} onPress={() => void onSave()}>Save for later</Button>
        </div>
      </form>
    </div>
  );
}

function Content() {
  const doc = useSearchParams().get("doc");
  if (!doc) return <StatusMessage>This page needs a document. Open it from your documents.</StatusMessage>;
  return <Editor doc={doc} />;
}

export default function FixPage() {
  return (
    <RequireAuth>
      {() => (
        <Page title="Fix a document" intro="Describe images, set the title and language, and correct heading levels. We build a fixed copy and check it again.">
          <p><NextLink href="/workspace/documents" className="underline">Back to your documents</NextLink></p>
          <Suspense><Content /></Suspense>
        </Page>
      )}
    </RequireAuth>
  );
}
