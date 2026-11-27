"use client";

import { useEffect, useState } from "react";
import { Button, ErrorSummary, Form, Select, StatusMessage, Table, TextField, notify } from "@a11y/ui";
import { get, post, put } from "@/lib/api";
import { formatDate } from "@/lib/billing";
import { useApi } from "@/lib/useApi";
import { useForm } from "../useForm";
import { SchemaForm, prepare, type Json, type Schema } from "./SchemaForm";

interface Def { key: string; description: string; scopes: string[]; owner_role: string; high_risk: boolean; tags: string[]; schema: Schema }
interface Loaded { source: string; version: number | null; value: Json }
interface Version { version: number; status: string; comment: string; created_at: string; published_at: string | null; restored_from: number | null }

const SCOPE_LABEL: Record<string, string> = { global: "Everyone (global)", plan: "One plan", org: "One organisation" };

export function SettingsTab() {
  const defs = useApi<Def[]>("/admin/settings");
  const [key, setKey] = useState<string | null>(null);
  const [scope, setScope] = useState("global");
  const [scopeId, setScopeId] = useState("");
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [value, setValue] = useState<Json>(null);
  const [history, setHistory] = useState<Version[]>([]);
  const [comment, setComment] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const form = useForm();

  const def = defs.data?.find((d) => d.key === key) ?? null;
  const needsId = scope !== "global";
  const ready = def !== null && (!needsId || scopeId.trim() !== "");
  const target = { scope, scope_id: needsId ? scopeId.trim() : "" };

  async function load() {
    if (!def) return;
    const q = `scope=${scope}&scope_id=${encodeURIComponent(target.scope_id)}`;
    const [cur, hist] = await Promise.all([get<Loaded>(`/admin/settings/${def.key}?${q}`), get<Version[]>(`/admin/settings/${def.key}/history?${q}`)]);
    if (!cur.ok) { setLoaded(null); setLoadError(cur.problem.detail); return; }
    setLoadError(null);
    setLoaded(cur.data);
    // The server returns the effective value; for a never-set setting that is the code default
    // (JSON Schema omits default_factory values, so the schema alone would lose them).
    setValue(cur.data.value);
    setHistory(hist.ok ? hist.data : []);
  }
  // Reload only when the target changes.
  useEffect(() => { setLoaded(null); if (ready) void load(); }, [key, scope, scopeId, defs.data]);

  return (
    <div className="flex flex-col gap-6">
      <p className="max-w-3xl text-fg-muted">Every setting is versioned and audited. A change applies to the next job with no redeploy. Secrets are write-only: once saved they are never shown again.</p>
      <div className="grid max-w-3xl gap-4 sm:grid-cols-2">
        <Select label="Setting" value={key} onChange={(k) => { setKey(k ? String(k) : null); setScope("global"); setScopeId(""); }}
          options={(defs.data ?? []).map((d) => ({ id: d.key, label: `${d.key}${d.high_risk ? " (high risk)" : ""}` }))} />
        {def && (
          <Select label="Applies to" value={scope} onChange={(k) => { setScope(String(k)); setScopeId(""); }}
            options={def.scopes.map((s) => ({ id: s, label: SCOPE_LABEL[s] ?? s }))} />
        )}
        {def && needsId && (
          <TextField id="field-scope_id" label={scope === "plan" ? "Plan id" : "Organisation id"} description={scope === "plan" ? "For example GROWTH." : "The organisation's UUID."} value={scopeId} onChange={setScopeId} />
        )}
      </div>

      {def && <p className="max-w-3xl">{def.description} Managed by: {def.owner_role.replace(/_/g, " ").toLowerCase()}.</p>}
      {loadError && <StatusMessage>{loadError}</StatusMessage>}

      {def && loaded && (
        <>
          <p role="status" className="font-semibold">Current value comes from: {loaded.source}</p>
          <ErrorSummary errors={form.errors} />
          <Form
            className="flex max-w-3xl flex-col gap-4"
            onSubmit={async (e) => {
              e.preventDefault();
              const ok = await form.submit(async () => {
                const r = await put(`/admin/settings/${def.key}`, { ...target, value: prepare(value), comment, publish: true });
                return r.ok ? null : { ...r.problem, field: undefined };
              });
              if (ok) { notify({ title: "Setting published", description: `${def.key} is live.`, kind: "success" }); setComment(""); void load(); }
            }}
          >
            <SchemaForm schema={def.schema} value={value} onChange={setValue} idPrefix="setting" />
            <TextField id="field-comment" label="Why are you changing this? (required)" value={comment} onChange={setComment} isRequired />
            <Button type="submit" isPending={form.submitting} pendingLabel="Publishing">Publish change</Button>
          </Form>

          <section aria-labelledby="history" className="flex flex-col gap-3">
            <h2 id="history" className="text-xl font-bold">History</h2>
            <Table<Version>
              label={`Version history of ${def.key}`}
              rows={history}
              rowKey={(v) => v.version}
              emptyText="This setting has never been changed, so the built-in default applies."
              columns={[
                { id: "v", header: "Version", isRowHeader: true, render: (v) => `v${v.version}` },
                { id: "s", header: "Status", render: (v) => v.status },
                { id: "w", header: "When", render: (v) => formatDate(v.published_at ?? v.created_at) },
                { id: "c", header: "Why", render: (v) => v.comment + (v.restored_from ? ` (restored from v${v.restored_from})` : "") },
                {
                  id: "a", header: "Action",
                  render: (v) => v.status === "published" ? (
                    <Button variant="secondary" isDisabled={!comment.trim()} onPress={async () => {
                      const r = await post(`/admin/settings/${def.key}/rollback`, { ...target, to_version: v.version, comment });
                      if (r.ok) { notify({ title: `Restored version ${v.version}`, kind: "success" }); setComment(""); void load(); }
                      else notify({ title: "Could not roll back", description: r.problem.detail, kind: "error" });
                    }}>Roll back<span className="a11y-sr-only"> to version {v.version}</span></Button>
                  ) : null,
                },
              ]}
            />
            <p className="text-sm text-fg-muted">To roll back, write the reason in the box above first, then choose a version. History is never deleted: a rollback publishes a new version.</p>
          </section>
        </>
      )}
    </div>
  );
}
