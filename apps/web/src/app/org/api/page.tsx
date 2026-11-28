"use client";

import NextLink from "next/link";
import { useRef, useState } from "react";
import { Button, Checkbox, Dialog, DialogTrigger, ErrorSummary, Form, Select, StatusMessage, Table, TextField, notify } from "@a11y/ui";
import { Page } from "@/components/Page";
import { RequireAuth } from "@/components/RequireAuth";
import { useForm } from "@/components/useForm";
import { del, post } from "@/lib/api";
import type { ApiKeyList, ApiKeyRow, NewKey } from "@/lib/apiKeys";
import { formatDate } from "@/lib/billing";
import { useApi } from "@/lib/useApi";

const EXPIRY = [{ id: "30", label: "30 days" }, { id: "90", label: "90 days" }, { id: "365", label: "1 year" }, { id: "none", label: "No expiry" }];
const STATE: Record<string, string> = { active: "Active", expired: "Expired", revoked: "Revoked" };

function Content() {
  const state = useApi<ApiKeyList>("/org/api-keys");
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(["scans:read"]);
  const [expiry, setExpiry] = useState("90");
  const [created, setCreated] = useState<NewKey | null>(null);
  const [message, setMessage] = useState("");
  const reveal = useRef<HTMLHeadingElement>(null);
  const form = useForm();

  if (state.error) return <StatusMessage>{state.error.detail}</StatusMessage>;
  if (!state.data) return <p role="status">Loading.</p>;
  const d = state.data;
  if (!d.entitled) {
    return <StatusMessage>API access is not part of your current plan. <NextLink href={d.upgrade_url} className="underline">See plans</NextLink>.</StatusMessage>;
  }
  const active = d.keys.filter((k) => k.state === "active").length;
  const cap = d.max_lifetime_days;

  async function revoke(k: ApiKeyRow, close: () => void) {
    const r = await del(`/org/api-keys/${k.id}`);
    close();
    if (r.ok) { setMessage(`The key “${k.name}” was revoked. It stops working immediately.`); void state.reload(); }
    else setMessage(r.problem.detail);
  }

  return (
    <div className="flex max-w-4xl flex-col gap-8">
      <p>
        API keys let your own systems start scans and read results without signing in. Each key works only for this organisation and only for the permissions you give it.
        Read the <NextLink href="/developers" className="underline">API reference</NextLink> for what you can do.
      </p>

      {created && (
        <section aria-labelledby="new-key" className="flex flex-col gap-3 rounded border-2 border-border p-4">
          <h2 id="new-key" ref={reveal} tabIndex={-1} className="text-xl font-bold">Your new key: copy it now</h2>
          <p><strong>This is the only time the key is shown.</strong> We keep only a fingerprint, so a lost key cannot be recovered, only replaced. Store it in a secret manager, never in source code.</p>
          <p><code className="block [overflow-wrap:anywhere] rounded border border-border bg-surface-raised p-3 select-all">{created.key}</code></p>
          <div className="flex flex-wrap gap-3">
            <Button variant="secondary" onPress={async () => { await navigator.clipboard?.writeText(created.key); notify({ title: "Key copied", kind: "success" }); }}>Copy key</Button>
            <Button variant="secondary" onPress={() => { setCreated(null); setMessage(`The key “${created.name}” was created.`); }}>I have stored it safely</Button>
          </div>
        </section>
      )}

      <section aria-labelledby="keys" className="flex flex-col gap-3">
        <h2 id="keys" className="text-xl font-bold">Your keys</h2>
        <p role="status">{message || `${active} of ${d.max_keys} active keys.`}</p>
        <Table<ApiKeyRow>
          label="API keys"
          rows={d.keys}
          rowKey={(k) => k.id}
          emptyText="You have no keys yet."
          columns={[
            { id: "n", header: "Name", isRowHeader: true, render: (k) => <>{k.name} <span className="text-fg-muted">(ends …{k.hint})</span></> },
            { id: "s", header: "Permissions", render: (k) => k.scopes.join(", ") },
            { id: "st", header: "State", render: (k) => STATE[k.state] },
            { id: "u", header: "Last used", render: (k) => (k.last_used_at ? formatDate(k.last_used_at) : "Never") },
            { id: "e", header: "Expires", render: (k) => (k.expires_at ? formatDate(k.expires_at) : "Never") },
            {
              id: "a", header: "Action",
              render: (k) => k.state === "active" ? (
                <DialogTrigger>
                  <Button variant="secondary">Revoke<span className="a11y-sr-only"> key {k.name}</span></Button>
                  <Dialog title={`Revoke “${k.name}”?`}>
                    {(close) => (
                      <>
                        <p>Anything using this key stops working immediately. This cannot be undone: you would need to create a new key.</p>
                        <div className="flex gap-3"><Button onPress={() => void revoke(k, close)}>Revoke key</Button></div>
                      </>
                    )}
                  </Dialog>
                </DialogTrigger>
              ) : null,
            },
          ]}
        />
      </section>

      <section aria-labelledby="create" className="flex max-w-xl flex-col gap-3">
        <h2 id="create" className="text-xl font-bold">Create a key</h2>
        <ErrorSummary errors={form.errors} />
        <Form
          className="flex flex-col gap-4"
          onSubmit={async (e) => {
            e.preventDefault();
            if (scopes.length === 0) { await form.submit(async () => ({ detail: "Choose at least one permission.", field: "scopes" })); return; }
            const ok = await form.submit(async () => {
              const r = await post<NewKey>("/org/api-keys", { name, scopes, expires_in_days: expiry === "none" ? null : Number(expiry) });
              if (!r.ok) return r.problem;
              setCreated(r.data);
              return null;
            });
            if (ok) { setName(""); void state.reload(); requestAnimationFrame(() => reveal.current?.focus()); }
          }}
        >
          <TextField id="field-name" label="Name" description="Where it will be used, for example “Build pipeline”." value={name} onChange={setName} isRequired error={form.fieldError("name")} />
          <fieldset id="field-scopes" className="flex flex-col gap-1">
            <legend className="font-semibold">Permissions</legend>
            {Object.entries(d.scopes).map(([id, label]) => (
              <Checkbox key={id} label={`${label} (${id})`} isSelected={scopes.includes(id)} onChange={(on) => setScopes((s) => (on ? [...s, id] : s.filter((x) => x !== id)))} />
            ))}
            {form.fieldError("scopes") && <p className="text-sm font-medium text-danger">{form.fieldError("scopes")}</p>}
          </fieldset>
          <Select label="Expires" value={expiry} onChange={(k) => setExpiry(String(k))} options={cap ? EXPIRY.filter((x) => x.id !== "none" && Number(x.id) <= cap) : EXPIRY} />
          <Button type="submit" isPending={form.submitting} pendingLabel="Creating key" isDisabled={active >= d.max_keys}>Create key</Button>
          {active >= d.max_keys && <p>You have the most keys your organisation can have. Revoke one to create another.</p>}
        </Form>
      </section>
    </div>
  );
}

export default function ApiKeysPage() {
  return (
    <RequireAuth requiredRole="COMPANY_ADMIN">
      {() => (
        <Page title="API keys" intro="Let your own systems start scans and read results.">
          <p><NextLink href="/org" className="underline">Back to your organisation</NextLink></p>
          <Content />
        </Page>
      )}
    </RequireAuth>
  );
}
