"use client";

import NextLink from "next/link";
import { useEffect, useState } from "react";
import { Button, ErrorSummary, Form, StatusMessage, notify } from "@a11y/ui";
import { SchemaForm, prepare, type Json, type Schema } from "@/components/admin/SchemaForm";
import { Page } from "@/components/Page";
import { ProviderTest } from "@/components/ProviderTest";
import { RequireAuth } from "@/components/RequireAuth";
import { useForm } from "@/components/useForm";
import { put } from "@/lib/api";
import { useApi } from "@/lib/useApi";

interface ByokState {
  eligible: boolean; upgrade_url: string; schema?: Schema; value?: Json; version?: number | null;
  usage_this_month?: { calls: number; tokens: number };
}

function Content() {
  const state = useApi<ByokState>("/org/ai");
  const [value, setValue] = useState<Json>(null);
  const form = useForm();
  useEffect(() => { if (state.data?.value) setValue(state.data.value); }, [state.data]);

  if (state.error) return <StatusMessage>{state.error.detail}</StatusMessage>;
  if (!state.data) return <p role="status">Loading.</p>;
  if (!state.data.eligible) {
    return (
      <StatusMessage>
        Using your own AI accounts is part of the Enterprise plan. <NextLink href="/help" className="underline">Contact us</NextLink> to upgrade.
      </StatusMessage>
    );
  }
  const providers = ((value as { providers?: Array<{ id: string; display_name: string }> } | null)?.providers ?? []);
  const saved = ((state.data.value as { providers?: Array<{ id: string; display_name: string }> } | undefined)?.providers ?? []);
  const usage = state.data.usage_this_month;

  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <p>
        Use your own OpenAI, Azure OpenAI or DeepSeek account for AI features in this organisation. Your requests then go to <em>your</em> account and
        are billed by your provider. Keys are stored encrypted, are never shown again after saving, and are used only for your organisation.
      </p>
      {usage && <p>This month: {usage.calls} AI {usage.calls === 1 ? "call" : "calls"} on your own accounts ({usage.tokens.toLocaleString("en-IN")} tokens).</p>}
      <ErrorSummary errors={form.errors} />
      <Form
        className="flex flex-col gap-4"
        onSubmit={async (e) => {
          e.preventDefault();
          const ok = await form.submit(async () => {
            const r = await put("/org/ai", { value: prepare(value) });
            return r.ok ? null : { ...r.problem, field: undefined };
          });
          if (ok) { notify({ title: "Saved", description: "Your AI settings are live.", kind: "success" }); void state.reload(); }
        }}
      >
        {state.data.schema && <SchemaForm schema={state.data.schema} value={value ?? {}} onChange={setValue} idPrefix="byok" />}
        <Button type="submit" isPending={form.submitting} pendingLabel="Saving">Save AI settings</Button>
      </Form>

      <section aria-labelledby="test" className="flex flex-col gap-3">
        <h2 id="test" className="text-xl font-bold">Test your connection</h2>
        {saved.length === 0 ? <p className="text-fg-muted">Save a provider first, then test it here.</p> : saved.map((p) => (
          <div key={p.id}><p className="font-semibold">{p.display_name}</p><ProviderTest path="/org/ai/test" body={{ provider_id: p.id }} name={p.display_name} /></div>
        ))}
        {providers.length !== saved.length && <p className="text-sm text-fg-muted">Providers you have added but not yet saved cannot be tested.</p>}
      </section>
    </div>
  );
}

export default function OrgAiPage() {
  return (
    <RequireAuth requiredRole="COMPANY_ADMIN">
      {() => <Page title="AI provider" intro="Bring your own AI accounts (Enterprise)."><Content /></Page>}
    </RequireAuth>
  );
}
