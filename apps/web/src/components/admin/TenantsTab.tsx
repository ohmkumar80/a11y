"use client";

import { useState } from "react";
import { Button, ErrorSummary, Form, Select, Table, TextField, notify } from "@a11y/ui";
import { post } from "@/lib/api";
import { STATUS_LABEL, formatDate, type SubStatus } from "@/lib/billing";
import { useApi } from "@/lib/useApi";
import { useForm } from "../useForm";

interface Tenant { id: string; name: string; plan_id: string | null; status: SubStatus | null; trial_ends_at: string | null; active_users: number }
interface Funnel { by_status: Record<string, number>; signups_last_30_days: number; trials_ending_within_7_days: number }
interface Plan { id: string; name: string; is_active: boolean }

export function TenantsTab() {
  const tenants = useApi<Tenant[]>("/admin/tenants");
  const funnel = useApi<Funnel>("/admin/trial-funnel");
  const plans = useApi<Plan[]>("/admin/plans");
  const [org, setOrg] = useState<string | null>(null);
  const [plan, setPlan] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("ACTIVE");
  const [comment, setComment] = useState("");
  const form = useForm();

  return (
    <div className="flex flex-col gap-8">
      <section aria-labelledby="funnel" className="flex flex-col gap-2">
        <h2 id="funnel" className="text-xl font-bold">Trial funnel</h2>
        {funnel.data ? (
          <dl className="grid max-w-xl grid-cols-[1fr_max-content] gap-x-6 gap-y-1">
            {Object.entries(funnel.data.by_status).map(([s, n]) => (
              <div key={s} className="contents"><dt>{STATUS_LABEL[s as SubStatus] ?? s}</dt><dd className="font-semibold">{n}</dd></div>
            ))}
            <dt>New organisations in the last 30 days</dt><dd className="font-semibold">{funnel.data.signups_last_30_days}</dd>
            <dt>Trials ending within 7 days</dt><dd className="font-semibold">{funnel.data.trials_ending_within_7_days}</dd>
          </dl>
        ) : <p role="status">Loading funnel.</p>}
      </section>

      <section aria-labelledby="tenants" className="flex flex-col gap-3">
        <h2 id="tenants" className="text-xl font-bold">Organisations</h2>
        <Table<Tenant>
          label="Organisations"
          rows={tenants.data ?? []}
          rowKey={(t) => t.id}
          emptyText={tenants.data ? "No organisations yet." : "Loading organisations."}
          columns={[
            { id: "name", header: "Name", isRowHeader: true, render: (t) => t.name },
            { id: "plan", header: "Plan", render: (t) => t.plan_id ?? "None" },
            { id: "status", header: "Status", render: (t) => (t.status ? STATUS_LABEL[t.status] : "None") },
            { id: "trial", header: "Trial ends", render: (t) => (t.trial_ends_at ? formatDate(t.trial_ends_at) : "Not applicable") },
            { id: "users", header: "Active users", render: (t) => t.active_users },
          ]}
        />
      </section>

      <section aria-labelledby="assign" className="flex max-w-md flex-col gap-3">
        <h2 id="assign" className="text-xl font-bold">Assign a plan</h2>
        <p className="text-fg-muted">Use this after you have invoiced a customer. The change is recorded in the audit log with your note.</p>
        <ErrorSummary errors={form.errors} />
        <Form
          className="flex flex-col gap-4"
          onSubmit={async (e) => {
            e.preventDefault();
            if (!org || !plan) return;
            const ok = await form.submit(async () => {
              const r = await post(`/admin/tenants/${org}/plan`, { plan_id: plan, status, comment });
              return r.ok ? null : r.problem;
            });
            if (ok) {
              notify({ title: "Plan assigned", kind: "success" });
              setComment("");
              void tenants.reload();
              void funnel.reload();
            }
          }}
        >
          <Select label="Organisation" isRequired value={org} onChange={(k) => setOrg(k ? String(k) : null)} options={(tenants.data ?? []).map((t) => ({ id: t.id, label: t.name }))} />
          <Select label="Plan" isRequired value={plan} onChange={(k) => setPlan(k ? String(k) : null)} options={(plans.data ?? []).filter((p) => p.is_active).map((p) => ({ id: p.id, label: p.name }))} error={form.fieldError("plan_id")} />
          <Select label="Status" value={status} onChange={(k) => setStatus(String(k))} options={(["ACTIVE", "TRIALING", "PAST_DUE", "LOCKED_READ_ONLY"] as const).map((s) => ({ id: s, label: STATUS_LABEL[s] }))} />
          <TextField id="field-comment" label="Why (for the audit log)" description="For example: invoice 42 paid." value={comment} onChange={setComment} isRequired />
          <Button type="submit" isPending={form.submitting} pendingLabel="Assigning plan" isDisabled={!org || !plan}>Assign plan</Button>
        </Form>
      </section>
    </div>
  );
}
