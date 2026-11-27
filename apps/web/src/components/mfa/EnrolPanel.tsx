"use client";

import { useEffect, useState } from "react";
import { Button, ErrorSummary, Form, StatusMessage, TextField, notify } from "@a11y/ui";
import type { EnrolInfo, Problem } from "@/lib/api";
import { useForm } from "../useForm";

/**
 * Text-first enrolment: the key is shown as text to type into an authenticator app, with a link that opens
 * the app. A QR code is deliberately NOT the only way (it excludes blind and low-vision people).
 */
export function EnrolPanel({
  start, confirm, submitLabel = "Turn on two-step verification",
}: {
  start: () => Promise<{ info: EnrolInfo } | { problem: Problem }>;
  confirm: (code: string) => Promise<Problem | null>;
  submitLabel?: string;
}) {
  const [info, setInfo] = useState<EnrolInfo | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const form = useForm();

  useEffect(() => {
    let live = true;
    void start().then((r) => { if (!live) return; if ("info" in r) setInfo(r.info); else setStartError(r.problem.detail); });
    return () => { live = false; };
  }, [start]);

  if (startError) return <StatusMessage>{startError}</StatusMessage>;
  if (!info) return <p role="status">Preparing your setup key.</p>;

  return (
    <div className="flex max-w-xl flex-col gap-4">
      <ol className="list-decimal pl-5 [&>li]:mb-2">
        <li>Open an authenticator app on your phone or computer (for example your password manager, Google Authenticator, Microsoft Authenticator or Authy).</li>
        <li>
          Add an account and choose &ldquo;enter a setup key&rdquo;. Use this key, with the account name <strong>{info.account}</strong>:
          <p className="my-2"><code className="rounded border-2 border-border px-2 py-1 text-lg tracking-wide [overflow-wrap:anywhere]" aria-label={`Setup key: ${info.key.replace(/ /g, ", ")}`}>{info.key}</code></p>
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="secondary" onPress={async () => { await navigator.clipboard?.writeText(info.key.replace(/ /g, "")); notify({ title: "Setup key copied", kind: "success" }); }}>Copy setup key</Button>
            <a href={info.otpauth_uri} className="inline-flex min-h-11 items-center underline">Open in my authenticator app<span className="a11y-sr-only"> (uses an otpauth link)</span></a>
          </div>
        </li>
        <li>Enter the 6-digit code the app shows now. It changes every 30 seconds.</li>
      </ol>
      <ErrorSummary errors={form.errors} />
      <Form
        className="flex flex-col gap-4"
        onSubmit={async (e) => {
          e.preventDefault();
          const ok = await form.submit(() => confirm(code));
          if (ok) setCode("");
        }}
      >
        <TextField id="field-code" label="6-digit code" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={setCode} isRequired error={form.fieldError("code")}
          description="You can paste the code. Spaces are fine." />
        <div><Button type="submit" isPending={form.submitting} pendingLabel="Checking the code">{submitLabel}</Button></div>
      </Form>
    </div>
  );
}
