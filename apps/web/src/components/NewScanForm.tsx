"use client";

import NextLink from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, Checkbox, ErrorSummary, Form, Select, StatusMessage, TextField } from "@a11y/ui";
import { post, type Problem } from "@/lib/api";
import { type StandardInfo } from "@/lib/scans";
import { useFlags } from "@/lib/flags";
import { useApi } from "@/lib/useApi";
import { Tip } from "./Tip";
import { useForm } from "./useForm";

/** Structured errors from the API get a next step, not just a message (seat limit, quota, verification...). */
function NextStep({ problem }: { problem: Problem }) {
  const code = problem.code;
  if (code === "quota_exceeded" || code === "subscription_locked") {
    return <StatusMessage>{problem.detail} <NextLink href="/org" className="underline">See your plan</NextLink>.</StatusMessage>;
  }
  if (code === "domain_not_verified") {
    return <StatusMessage>{problem.detail} <a href="#domains" className="underline">Verify your site</a> below, or scan fewer pages.</StatusMessage>;
  }
  return null;
}

/** Standards are grouped by what they mean for you, so a long list stays easy to scan. */
const GROUPS = [
  { id: "reference", title: "Reference standard", help: "The baseline most audits start from." },
  { id: "regulation", title: "Legal requirements", help: "Rules a law points to. Choose these if a regulator or customer will ask." },
  { id: "recommended_target", title: "Recommended targets", help: "Not required by law, but widely expected." },
  { id: "benchmark", title: "Benchmarks", help: "Useful comparisons. Not a legal requirement." },
  { id: "informational", title: "Informational", help: "For reference only." },
] as const;

export function NewScanForm({ canVerify }: { canVerify: boolean }) {
  const router = useRouter();
  const standards = useApi<{ standards: StandardInfo[] }>("/standards");
  const flags = useFlags();
  const [url, setUrl] = useState("");
  const [picked, setPicked] = useState<string[]>(["WCAG_2_2_AA"]);
  const [mode, setMode] = useState("single");
  const [pages, setPages] = useState("5");
  const [structured, setStructured] = useState<Problem | null>(null);
  const form = useForm();

  const list = standards.data?.standards ?? [];
  const known: string[] = GROUPS.map((g) => g.id);
  const inGroup = (g: (typeof GROUPS)[number]["id"]) => list.filter((s) => (known.includes(s.legal_status) ? s.legal_status : "informational") === g);

  return (
    <section id="new-scan" aria-labelledby="new-scan-h" className="flex flex-col gap-4 scroll-mt-4">
      <h2 id="new-scan-h">Start a scan</h2>
      <ErrorSummary errors={form.errors} />
      {structured && <NextStep problem={structured} />}
      <Form
        className="flex max-w-2xl flex-col gap-5"
        onSubmit={async (e) => {
          e.preventDefault();
          setStructured(null);
          let id = "";
          const ok = await form.submit(async () => {
            const r = await post<{ id: string }>("/scans", { url, standards: picked, mode, max_pages: mode === "crawl" ? Number(pages) : null });
            if (r.ok) { id = r.data.id; return null; }
            setStructured(r.problem);
            return r.problem;
          });
          if (ok) router.push(`/workspace/scan?id=${id}`);
        }}
      >
        <TextField id="field-url" label="Web address" type="url" inputMode="url" autoComplete="off" value={url} onChange={setUrl} isRequired
          description="For example https://example.com. Only public websites can be scanned." error={form.fieldError("url")} />
        <Tip>Use the full address, starting with https://. If you are not sure where to begin, scan the page most visitors see first, such as your home page.</Tip>

        <fieldset className="flex flex-col gap-3">
          <legend className="font-bold">Check against</legend>
          <p className="text-sm text-fg-muted">Open a group to see its standards. You can change this later without scanning again.</p>
          {GROUPS.map((g) => {
            const items = inGroup(g.id);
            if (items.length === 0) return null;
            const chosen = items.filter((s) => picked.includes(s.id)).length;
            return (
              <details key={g.id} open={chosen > 0} className="group border-2 border-fg bg-bg">
                <summary className="flex min-h-11 cursor-default items-center justify-between gap-3 px-3 py-2 font-bold marker:content-none">
                  <span>{g.title}</span>
                  <span className="text-sm font-normal text-fg-muted">{chosen} of {items.length} selected</span>
                </summary>
                <div className="flex flex-col border-t border-border-subtle px-3 pb-2 pt-2">
                  <p className="text-sm text-fg-muted">{g.help}</p>
                  {items.map((s) => (
                    <Checkbox
                      key={s.id}
                      label={s.label}
                      description={`${s.criteria_count} criteria, ${s.automated_criteria} can be checked automatically${s.citation ? `. ${s.citation}` : ""}`}
                      isSelected={picked.includes(s.id)}
                      onChange={(on) => setPicked(on ? [...picked, s.id] : picked.filter((x) => x !== s.id))}
                    />
                  ))}
                </div>
              </details>
            );
          })}
          {list.length > 0 && picked.length === 0 && <p role="status" className="font-bold text-danger">Choose at least one standard.</p>}
        </fieldset>
        <Tip>Not sure? Keep the default, WCAG 2.2 Level AA. Add the others only if a law or a contract asks for them.</Tip>

        {flags.crawl_scans && <Select label="How far to scan" value={mode} onChange={(k) => setMode(String(k))} options={[{ id: "single", label: "This page only" }, { id: "crawl", label: "This page and the pages it links to on the same site" }]} />}
        {flags.crawl_scans && mode === "crawl" && (
          <TextField id="field-max_pages" label="Most pages to scan" type="number" inputMode="numeric" value={pages} onChange={setPages} isRequired
            description={canVerify ? "Larger crawls need you to verify the site first." : "Larger crawls need an administrator to verify the site first."} error={form.fieldError("max_pages")} />
        )}
        <Button type="submit" isPending={form.submitting} pendingLabel="Starting scan" isDisabled={picked.length === 0}>Start scan</Button>
      </Form>
    </section>
  );
}
