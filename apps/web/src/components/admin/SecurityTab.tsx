"use client";

import { useEffect, useState } from "react";
import { Button, ErrorSummary, Form, Select, StatusMessage, TextField, notify } from "@a11y/ui";
import { get, put } from "@/lib/api";
import { SecurityPanel } from "../mfa/SecurityPanel";
import { useForm } from "../useForm";

type Mode = "required" | "optional" | "off";
interface Policy { super_admin: Mode; org_admin: Mode; issuer: string }
const MODES = [
  { id: "required", label: "Required: everyone must set it up and enter a code" },
  { id: "optional", label: "Optional: only people who set it up are asked" },
  { id: "off", label: "Off: nobody is asked (development only)" },
];

/** The on/off control for administrator two-step verification, plus the signed-in admin's own settings. */
export function SecurityTab({ onChanged }: { onChanged: () => void }) {
  const [saved, setSaved] = useState<Policy | null>(null);
  const [draft, setDraft] = useState<Policy | null>(null);
  const [env, setEnv] = useState("");
  const [comment, setComment] = useState("");
  const form = useForm();

  const load = async () => {
    const [p, e] = await Promise.all([get<{ value: Policy }>("/admin/settings/auth.mfa"), get<{ environment: string }>("/admin/security/mfa")]);
    if (p.ok) { setSaved(p.data.value); setDraft(p.data.value); }
    if (e.ok) setEnv(e.data.environment);
  };
  useEffect(() => { void load(); }, []);

  if (!draft || !saved) return <p role="status">Loading security settings.</p>;
  const changed = draft.super_admin !== saved.super_admin || draft.org_admin !== saved.org_admin;
  const production = env === "production";

  return (
    <div className="flex flex-col gap-8">
      <section aria-labelledby="policy" className="flex max-w-2xl flex-col gap-3">
        <h2 id="policy" className="text-xl font-bold">Two-step verification policy</h2>
        <p className="text-fg-muted">Choose who must enter a code from an authenticator app when they sign in. Changes apply to the next sign-in. Everything is recorded in the audit log and can be rolled back in the Settings tab (<code>auth.mfa</code>).</p>
        <ErrorSummary errors={form.errors} />
        <Form className="flex flex-col gap-4" onSubmit={async (e) => {
          e.preventDefault();
          const ok = await form.submit(async () => {
            const r = await put("/admin/settings/auth.mfa", { scope: "global", scope_id: "", value: draft, comment, publish: true });
            return r.ok ? null : { ...r.problem, field: undefined };
          });
          if (ok) { notify({ title: "Policy saved", description: "It applies to the next sign-in.", kind: "success" }); setComment(""); await load(); onChanged(); }
        }}>
          <Select label="Platform administrators" value={draft.super_admin} onChange={(k) => setDraft({ ...draft, super_admin: String(k) as Mode })}
            options={MODES.filter((m) => !(production && m.id === "off"))} />
          <Select label="Organisation administrators" value={draft.org_admin} onChange={(k) => setDraft({ ...draft, org_admin: String(k) as Mode })} options={MODES} />
          {draft.super_admin === "off" && <StatusMessage>With this off, anyone who knows an administrator&apos;s password can use the admin console. Use it only while developing.</StatusMessage>}
          {production && <p className="text-sm text-fg-muted">Turning it off for platform administrators is not allowed in production.</p>}
          <TextField id="field-comment" label="Why are you changing this? (required)" value={comment} onChange={setComment} isRequired isDisabled={!changed} />
          <div><Button type="submit" isDisabled={!changed} isPending={form.submitting} pendingLabel="Saving policy">Save policy</Button></div>
        </Form>
        <p className="text-sm text-fg-muted">Locked out? On the server run <code>python -m a11y_api.admin_cli --mfa-super-admin off</code> (development) or <code>--reset-mfa you@example.com</code>.</p>
      </section>

      <section aria-labelledby="mine" className="flex flex-col gap-3">
        <h2 id="mine" className="text-xl font-bold">Your own two-step verification</h2>
        <SecurityPanel />
      </section>
    </div>
  );
}
