"use client";

import { useState } from "react";
import { Button, Checkbox, ErrorSummary, Form, Select, StatusMessage, Table, TextField, notify } from "@a11y/ui";
import { put } from "@/lib/api";
import { featureLabel } from "@/lib/billing";
import { useApi } from "@/lib/useApi";
import { useForm } from "../useForm";
import { SchemaForm, prepare, type Json, type Schema } from "./SchemaForm";

interface Ent { feature_key: string; enabled: boolean; limit_value: number | null }
interface Price { currency: string; cycle: "MONTHLY" | "ANNUAL"; amount_minor: number }
interface Plan { id: string; name: string; description: string; is_public: boolean; is_active: boolean; sort_order: number; entitlements: Ent[]; prices: Price[] }
interface Affected { organization_id: string; feature: string; used: number; new_limit: number }

const SCHEMA: Schema = {
  type: "object",
  properties: {
    name: { type: "string", maxLength: 100 },
    description: { type: "string", maxLength: 1000 },
    is_public: { type: "boolean", default: true },
    is_active: { type: "boolean", default: true },
    sort_order: { type: "integer", description: "Lower numbers are listed first." },
    entitlements: {
      type: "array",
      title: "Entitlements",
      description: "Quotas and features on this plan. Add any new feature key here; no code change is needed.",
      items: {
        type: "object",
        properties: {
          feature_key: { type: "string", description: "Lower-case letters, digits and underscores, e.g. urls_monthly or seats." },
          enabled: { type: "boolean", default: true },
          limit_value: { anyOf: [{ type: "integer", minimum: 0 }, { type: "null" }], description: "Leave empty for unlimited." },
        },
      },
    },
    prices: {
      type: "array",
      title: "Prices",
      items: {
        type: "object",
        properties: {
          currency: { type: "string", description: "Three letters, e.g. INR." },
          cycle: { type: "string", enum: ["MONTHLY", "ANNUAL"] },
          amount_minor: { type: "integer", minimum: 0, description: "In paise or cents: 499900 means ₹4,999.00." },
        },
      },
    },
  },
};

const toForm = (p: Plan): Json => ({ name: p.name, description: p.description, is_public: p.is_public, is_active: p.is_active, sort_order: p.sort_order, entitlements: p.entitlements as unknown as Json, prices: p.prices as unknown as Json });
const BLANK: Json = { name: "", description: "", is_public: true, is_active: true, sort_order: 10, entitlements: [{ feature_key: "seats", enabled: true, limit_value: 3 }], prices: [] };

export function PlansTab() {
  const plans = useApi<Plan[]>("/admin/plans");
  const [sel, setSel] = useState<string>("__new");
  const [newId, setNewId] = useState("");
  const [value, setValue] = useState<Json>(BLANK);
  const [comment, setComment] = useState("");
  const [affected, setAffected] = useState<Affected[] | null>(null);
  const [confirm, setConfirm] = useState(false);
  const form = useForm();

  const choose = (id: string) => {
    setSel(id); setAffected(null); setConfirm(false);
    const p = plans.data?.find((x) => x.id === id);
    setValue(p ? toForm(p) : BLANK);
  };
  const planId = sel === "__new" ? newId : sel;

  return (
    <div className="a11y-page-body flex flex-col gap-8">
      <section aria-labelledby="plans" className="flex flex-col gap-3">
        <h2 id="plans" className="text-xl font-bold">Plans</h2>
        <Table<Plan>
          label="Plans and their limits"
          rows={plans.data ?? []}
          rowKey={(p) => p.id}
          emptyText={plans.data ? "No plans." : "Loading plans."}
          columns={[
            { id: "name", header: "Plan", isRowHeader: true, render: (p) => `${p.name} (${p.id})` },
            { id: "state", header: "State", render: (p) => `${p.is_active ? "Active" : "Inactive"}, ${p.is_public ? "public" : "hidden"}` },
            { id: "ents", header: "Limits", render: (p) => p.entitlements.map((e) => `${featureLabel(e.feature_key)}: ${!e.enabled ? "off" : e.limit_value ?? "unlimited"}`).join("; ") },
            { id: "price", header: "Prices", render: (p) => (p.prices.length ? p.prices.map((x) => `${x.currency} ${(x.amount_minor / 100).toLocaleString("en-IN")} ${x.cycle.toLowerCase()}`).join("; ") : "Not set") },
          ]}
        />
      </section>

      <section aria-labelledby="edit-plan" className="flex max-w-2xl flex-col gap-3">
        <h2 id="edit-plan" className="text-xl font-bold">Edit a plan</h2>
        <Select label="Plan to edit" value={sel} onChange={(k) => choose(String(k))} options={[{ id: "__new", label: "New plan" }, ...(plans.data ?? []).map((p) => ({ id: p.id, label: `${p.name} (${p.id})` }))]} />
        <ErrorSummary errors={form.errors} />
        {affected && (
          <StatusMessage>
            <p className="font-semibold">These organisations already use more than the new limit:</p>
            <ul className="list-disc pl-5">
              {affected.map((a) => <li key={`${a.organization_id}-${a.feature}`}>{a.organization_id}: {featureLabel(a.feature)}, {a.used} used, new limit {a.new_limit}</li>)}
            </ul>
            <Checkbox label="Apply anyway. They will be blocked from further use until they are under the limit." isSelected={confirm} onChange={setConfirm} />
          </StatusMessage>
        )}
        <Form
          className="flex flex-col gap-4"
          onSubmit={async (e) => {
            e.preventDefault();
            const ok = await form.submit(async () => {
              const r = await put<Plan>(`/admin/plans/${planId}`, { ...(prepare(value) as object), comment, confirm_below_usage: confirm });
              if (r.ok) return null;
              if (r.problem.code === "limit_below_usage") setAffected((r.problem.body?.affected as Affected[]) ?? []);
              return r.problem;
            });
            if (ok) {
              notify({ title: "Plan saved", description: `${planId} was updated.`, kind: "success" });
              setComment(""); setAffected(null); setConfirm(false);
              void plans.reload();
            }
          }}
        >
          {sel === "__new" && <TextField id="field-plan_id" label="Plan id" description="Upper-case letters, digits and underscores, e.g. PRO. Cannot be changed later." value={newId} onChange={(v) => setNewId(v.toUpperCase())} isRequired error={form.fieldError("plan_id")} />}
          <SchemaForm schema={SCHEMA} value={value} onChange={setValue} idPrefix="field" />
          <TextField id="field-comment" label="Why (for the audit log)" value={comment} onChange={setComment} isRequired />
          <Button type="submit" isPending={form.submitting} pendingLabel="Saving plan">Save plan</Button>
        </Form>
      </section>
    </div>
  );
}
