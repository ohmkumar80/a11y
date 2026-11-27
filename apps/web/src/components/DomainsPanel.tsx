"use client";

import { useState } from "react";
import { Button, ErrorSummary, Form, StatusMessage, Table, TextField, notify } from "@a11y/ui";
import { post } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { useForm } from "./useForm";

interface Domain {
  id: string; host: string; verified: boolean; method: string | null;
  instructions: { file: { url: string; content: string }; meta: { tag: string } };
}

export function DomainsPanel() {
  const domains = useApi<Domain[]>("/domains");
  const [host, setHost] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const form = useForm();

  return (
    <section id="domains" aria-labelledby="domains-h" className="flex max-w-3xl flex-col gap-3">
      <h2 id="domains-h" className="text-xl font-bold">Verified sites</h2>
      <p className="text-fg-muted">Crawling more than a few pages needs proof that you own the site. Add your site, then publish the code we give you in either of the two ways shown.</p>
      <ErrorSummary errors={form.errors} />
      <Form
        className="flex flex-col gap-4"
        onSubmit={async (e) => {
          e.preventDefault();
          const ok = await form.submit(async () => { const r = await post("/domains", { host }); return r.ok ? null : r.problem; });
          if (ok) { setHost(""); void domains.reload(); }
        }}
      >
        <TextField id="field-host" label="Site to verify" description="A host name such as example.com" value={host} onChange={setHost} isRequired error={form.fieldError("host")} />
        <div><Button type="submit" isPending={form.submitting} pendingLabel="Adding site">Add site</Button></div>
      </Form>
      {msg && <StatusMessage>{msg}</StatusMessage>}
      <Table<Domain>
        label="Your sites"
        rows={domains.data ?? []}
        rowKey={(d) => d.id}
        emptyText={domains.data ? "No sites yet." : "Loading sites."}
        columns={[
          { id: "host", header: "Site", isRowHeader: true, render: (d) => d.host },
          { id: "state", header: "Status", render: (d) => (d.verified ? `Verified (${d.method === "file" ? "file" : "meta tag"})` : "Not verified yet") },
          {
            id: "how", header: "How to verify",
            render: (d) => d.verified ? "Done" : (
              <details>
                <summary className="inline-flex min-h-11 cursor-default items-center underline">Show instructions<span className="a11y-sr-only"> for {d.host}</span></summary>
                <p className="mt-2">Option 1: publish a text file at <code>{d.instructions.file.url}</code> containing exactly:</p>
                <pre className="overflow-x-auto rounded border border-border p-2"><code>{d.instructions.file.content}</code></pre>
                <p className="mt-2">Option 2: add this tag to your home page:</p>
                <pre className="overflow-x-auto rounded border border-border p-2"><code>{d.instructions.meta.tag}</code></pre>
              </details>
            ),
          },
          {
            id: "act", header: "Action",
            render: (d) => d.verified ? null : (
              <Button variant="secondary" onPress={async () => {
                const r = await post(`/domains/${d.id}/verify`);
                if (r.ok) { notify({ title: "Site verified", description: d.host, kind: "success" }); setMsg(null); void domains.reload(); }
                else setMsg(r.problem.detail);
              }}>Check now<span className="a11y-sr-only"> for {d.host}</span></Button>
            ),
          },
        ]}
      />
    </section>
  );
}
