"use client";

import { useState } from "react";
import { Button, Checkbox, ErrorSummary, Form, Select, StatusMessage, Table, TextField, notify } from "@a11y/ui";
import { post } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { useForm } from "../useForm";
import { ProviderTest } from "../ProviderTest";

interface Provider {
  id: string; type: string; display_name: string; base_url: string | null; is_enabled: boolean; key_set: boolean;
  data_policy: { processing_regions: string[]; zero_retention: boolean };
  models: Array<{ id: string; model_name: string; capabilities: string[]; is_enabled: boolean }>;
}
interface Presets { presets: Record<string, { label: string; needs_endpoint: boolean; default_model: string }>; tasks: Record<string, string[]> }
interface QuickResult { routed_tasks: string[]; skipped: Array<{ task: string; reason: string }> }

const taskLabel = (t: string) => t.replace(/_/g, " ");

export function AiTab() {
  const providers = useApi<Provider[]>("/admin/ai/providers");
  const presets = useApi<Presets>("/admin/ai/presets");
  const [preset, setPreset] = useState("deepseek");
  const [key, setKey] = useState("");
  const [endpoint, setEndpoint] = useState("");
  const [modelName, setModelName] = useState("");
  const [tasks, setTasks] = useState<string[]>([]);
  const [comment, setComment] = useState("");
  const [result, setResult] = useState<QuickResult | null>(null);
  const form = useForm();
  const pre = presets.data?.presets[preset];

  return (
    <div className="a11y-page-body flex flex-col gap-8">
      <section aria-labelledby="providers" className="flex flex-col gap-3">
        <h2 id="providers" className="text-xl font-bold">AI providers</h2>
        <Table<Provider>
          label="AI providers"
          rows={providers.data ?? []}
          rowKey={(p) => p.id}
          emptyText={providers.data ? "No providers yet. Use Quick add below." : "Loading providers."}
          columns={[
            { id: "name", header: "Provider", isRowHeader: true, render: (p) => `${p.display_name} (${p.type})` },
            { id: "key", header: "Key", render: (p) => (p.key_set ? "Set" : "Not set") },
            { id: "state", header: "State", render: (p) => (p.is_enabled ? "Enabled" : "Disabled") },
            { id: "data", header: "Data processed in", render: (p) => (p.data_policy.processing_regions.length ? p.data_policy.processing_regions.join(", ").toUpperCase() : "Not specified") },
            { id: "models", header: "Models", render: (p) => (p.models.length ? p.models.map((m) => `${m.model_name} (${m.capabilities.join(", ")})`).join("; ") : "None") },
            { id: "test", header: "Check", render: (p) => <ProviderTest path={`/admin/ai/providers/${p.id}/test`} name={p.display_name} /> },
          ]}
        />
        <p className="max-w-3xl text-fg-muted">Prices, fallbacks, per-plan and per-organisation routing, tiers and budgets are edited in the Settings tab (<code>ai.models</code>, <code>ai.route.*</code>). Set each model&apos;s prices there so cost reports are accurate.</p>
      </section>

      <section aria-labelledby="quick" className="flex max-w-xl flex-col gap-3">
        <h2 id="quick" className="text-xl font-bold">Quick add a provider</h2>
        <p className="text-fg-muted">Creates the provider and model, stores the key encrypted (write-only), and routes the tasks you choose. Adding the same provider again replaces its key.</p>
        <ErrorSummary errors={form.errors} />
        {result && (
          <StatusMessage kind="success">
            Saved. {result.routed_tasks.length ? `Now used for: ${result.routed_tasks.map(taskLabel).join(", ")}.` : "No tasks routed yet."}
            {result.skipped.map((s) => <span key={s.task} className="block">Skipped {taskLabel(s.task)}: {s.reason}.</span>)}
          </StatusMessage>
        )}
        <Form
          className="flex flex-col gap-4"
          onSubmit={async (e) => {
            e.preventDefault();
            setResult(null);
            const ok = await form.submit(async () => {
              const r = await post<QuickResult>("/admin/ai/quick-add", {
                preset, api_key: key, endpoint: pre?.needs_endpoint ? endpoint : null, model_name: modelName || null, use_for_tasks: tasks, comment,
              });
              if (r.ok) setResult(r.data);
              return r.ok ? null : r.problem;
            });
            if (ok) { notify({ title: "Provider saved", kind: "success" }); setKey(""); setComment(""); void providers.reload(); }
          }}
        >
          <Select label="Provider" value={preset} onChange={(k) => setPreset(String(k))} options={Object.entries(presets.data?.presets ?? {}).map(([id, p]) => ({ id, label: p.label }))} />
          <TextField id="field-api_key" label="API key" type="password" autoComplete="off" value={key} onChange={setKey} isRequired description="Shown only once. It is never displayed again." error={form.fieldError("api_key")} />
          {pre?.needs_endpoint && <TextField id="field-endpoint" label="Resource address" description="For example https://your-resource.openai.azure.com" value={endpoint} onChange={setEndpoint} isRequired error={form.fieldError("endpoint")} />}
          <TextField id="field-model_name" label={preset === "azure_openai" ? "Deployment name" : "Model name"} description={pre?.default_model ? `Leave empty to use ${pre.default_model}.` : "As shown in your provider's portal."} value={modelName} onChange={setModelName} isRequired={preset === "azure_openai"} error={form.fieldError("model_name")} />
          <fieldset className="flex flex-col gap-1">
            <legend className="font-semibold">Use for these tasks</legend>
            <p className="text-sm text-fg-muted">A task is skipped automatically if the model cannot do it (for example image tasks on a text-only model).</p>
            {Object.entries(presets.data?.tasks ?? {}).map(([t, needs]) => (
              <Checkbox key={t} label={`${taskLabel(t)} (needs ${needs.join(", ")})`} isSelected={tasks.includes(t)} onChange={(on) => setTasks(on ? [...tasks, t] : tasks.filter((x) => x !== t))} />
            ))}
          </fieldset>
          <TextField id="field-comment" label="Why (for the audit log)" value={comment} onChange={setComment} isRequired />
          <Button type="submit" isPending={form.submitting} pendingLabel="Saving provider">Save provider</Button>
        </Form>
      </section>
    </div>
  );
}
