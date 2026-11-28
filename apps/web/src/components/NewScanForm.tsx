"use client";

import NextLink from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, Checkbox, ErrorSummary, Form, Select, StatusMessage, TextField } from "@a11y/ui";
import { post, type Problem } from "@/lib/api";
import { LEGAL_LABEL, type StandardInfo } from "@/lib/scans";
import { useFlags } from "@/lib/flags";
import { useApi } from "@/lib/useApi";
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

  return (
    <section aria-labelledby="new-scan" className="flex max-w-2xl flex-col gap-3">
      <h2 id="new-scan" className="text-xl font-bold">New scan</h2>
      <ErrorSummary errors={form.errors} />
      {structured && <NextStep problem={structured} />}
      <Form
        className="flex flex-col gap-4"
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
        <fieldset className="flex flex-col gap-1">
          <legend className="font-semibold">Check against</legend>
          <p className="text-sm text-fg-muted">You can change this later without scanning again.</p>
          {(standards.data?.standards ?? []).map((s) => (
            <Checkbox key={s.id} label={`${s.label}: ${LEGAL_LABEL[s.legal_status] ?? s.legal_status}`} isSelected={picked.includes(s.id)}
              onChange={(on) => setPicked(on ? [...picked, s.id] : picked.filter((x) => x !== s.id))} />
          ))}
        </fieldset>
        {flags.crawl_scans && <Select label="Scan" value={mode} onChange={(k) => setMode(String(k))} options={[{ id: "single", label: "This page only" }, { id: "crawl", label: "This page and the pages it links to on the same site" }]} />}
        {flags.crawl_scans && mode === "crawl" && (
          <TextField id="field-max_pages" label="Most pages to scan" type="number" inputMode="numeric" value={pages} onChange={setPages} isRequired
            description={canVerify ? "Larger crawls need you to verify the site first." : "Larger crawls need an administrator to verify the site first."} error={form.fieldError("max_pages")} />
        )}
        <Button type="submit" isPending={form.submitting} pendingLabel="Starting scan" isDisabled={picked.length === 0}>Start scan</Button>
      </Form>
    </section>
  );
}
