"use client";

import NextLink from "next/link";
import { useRef, useState } from "react";
import { Button, ErrorSummary, Form } from "@a11y/ui";
import { postFile, type Problem } from "@/lib/api";
import { KIND_LABEL, type UploadPolicy } from "@/lib/documents";
import { useApi } from "@/lib/useApi";
import { useForm } from "./useForm";

/** Choose a file and send it. The limits come from the server (an administrator can change them per plan), so the
 *  form explains them before anything is sent; the server is still the one that enforces them. */
export function DocumentUpload({ onUploaded }: { onUploaded: () => void }) {
  const policy = useApi<UploadPolicy>("/documents/policy");
  const [file, setFile] = useState<File | null>(null);
  const [message, setMessage] = useState("");
  const [structured, setStructured] = useState<Problem | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const form = useForm();
  const p = policy.data;

  if (policy.error) return <p role="alert">{policy.error.detail}</p>;
  if (!p) return <p role="status">Loading.</p>;
  if (!p.enabled) return <p role="status">Document uploads are switched off at the moment.</p>;
  const accept = p.kinds.map((k) => `.${k.kind}`).join(",");

  return (
    <section aria-labelledby="upload" className="flex max-w-2xl flex-col gap-3">
      <h2 id="upload" className="text-xl font-bold">Upload a document</h2>
      <ul className="list-disc pl-6 text-fg-muted">
        {p.kinds.map((k) => <li key={k.kind}>{KIND_LABEL[k.kind] ?? k.kind}: up to {k.max_mb} MB</li>)}
        <li>Up to {p.max_pages} pages or slides per file.</li>
        <li>Files are stored in {p.region?.label ?? "our default region"} and deleted after {p.retention_days} days. You can delete one sooner at any time.</li>
        <li><NextLink href="/org/data-policy" className="underline">Your data policy</NextLink> sets how long files are kept, where, and who may open them.</li>
      </ul>
      <ErrorSummary errors={form.errors} />
      {structured && (structured.code === "quota_exceeded" || structured.code === "subscription_locked") && (
        <p><NextLink href="/org" className="underline">See your plan</NextLink>.</p>
      )}
      <Form
        className="flex flex-col gap-4"
        onSubmit={async (e) => {
          e.preventDefault();
          if (!file) return;
          setMessage("");
          setStructured(null);
          const ok = await form.submit(async () => {
            const r = await postFile(`/documents?filename=${encodeURIComponent(file.name)}`, file);
            if (r.ok) return null;
            setStructured(r.problem);
            return { ...r.problem, field: "file" };
          });
          if (ok) {
            setMessage(`“${file.name}” was uploaded. We are checking it now; this usually takes a few seconds.`);
            setFile(null);
            if (input.current) input.current.value = "";
            onUploaded();
          }
        }}
      >
        <div className="flex flex-col gap-1">
          <label htmlFor="field-file" className="font-semibold">File</label>
          <input
            id="field-file"
            ref={input}
            type="file"
            accept={accept}
            aria-describedby={form.fieldError("file") ? "file-error" : undefined}
            aria-invalid={form.fieldError("file") ? true : undefined}
            onChange={(e) => { setFile(e.target.files?.[0] ?? null); setMessage(""); }}
            className="min-h-11 rounded-lg border-2 border-border bg-bg p-2"
          />
          {form.fieldError("file") && <p id="file-error" className="text-danger">{form.fieldError("file")}</p>}
        </div>
        <Button type="submit" isPending={form.submitting} pendingLabel="Uploading" isDisabled={!file}>Upload</Button>
      </Form>
      <p role="status" className="min-h-6">{message}</p>
    </section>
  );
}
