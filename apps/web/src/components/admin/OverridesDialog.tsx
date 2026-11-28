"use client";

import { useState } from "react";
import { Button, Checkbox, Dialog, DialogTrigger, ErrorSummary, Form, Select, Table, TextField, notify } from "@a11y/ui";
import { del, put } from "@/lib/api";
import { featureLabel, formatDate } from "@/lib/billing";
import { useApi } from "@/lib/useApi";
import { useForm } from "../useForm";

interface Override { feature: string; enabled: boolean; limit_value: number | null; expires_at: string | null; reason: string; expired: boolean }
interface Plan { entitlements: Array<{ feature_key: string }> }

const describe = (o: Override) => (!o.enabled ? "Switched off" : o.limit_value === null ? "On, no limit" : `On, up to ${o.limit_value.toLocaleString("en-IN")}`);

function Body({ orgId }: { orgId: string }) {
  const list = useApi<Override[]>(`/admin/tenants/${orgId}/overrides`);
  const plans = useApi<Plan[]>("/admin/plans");
  const [feature, setFeature] = useState<string | null>(null);
  const [enabled, setEnabled] = useState(true);
  const [limit, setLimit] = useState("");
  const [until, setUntil] = useState("");
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState("");
  const form = useForm();
  const features = [...new Set((plans.data ?? []).flatMap((p) => p.entitlements.map((e) => e.feature_key)))].sort();

  return (
    <div className="flex flex-col gap-4">
      <p>An exception replaces what the plan says for this organisation only, until it ends or you remove it. It is recorded in the audit log with your reason, and the organisation sees it in its own log.</p>
      <p role="status">{message}</p>
      <Table<Override>
        label="Exceptions for this organisation"
        rows={list.data ?? []}
        rowKey={(o) => o.feature}
        emptyText={list.data ? "None. This organisation gets exactly what its plan says." : "Loading."}
        columns={[
          { id: "f", header: "Feature", isRowHeader: true, render: (o) => featureLabel(o.feature) },
          { id: "s", header: "Setting", render: (o) => describe(o) },
          { id: "u", header: "Until", render: (o) => (o.expires_at ? `${formatDate(o.expires_at)}${o.expired ? " (ended)" : ""}` : "No end date") },
          { id: "r", header: "Reason", render: (o) => o.reason },
          {
            id: "x", header: "Remove",
            render: (o) => (
              <Button variant="secondary" isDisabled={!reason.trim()} onPress={async () => {
                const r = await del(`/admin/tenants/${orgId}/overrides/${o.feature}?reason=${encodeURIComponent(reason.trim())}`);
                setMessage(r.ok ? `The exception for ${featureLabel(o.feature)} was removed.` : r.problem.detail);
                if (r.ok) void list.reload();
              }}>Remove<span className="a11y-sr-only"> the exception for {featureLabel(o.feature)}</span></Button>
            ),
          },
        ]}
      />
      <p className="text-sm text-fg-muted">To remove an exception, type a reason below first.</p>
      <ErrorSummary errors={form.errors} />
      <Form
        className="flex flex-col gap-3"
        onSubmit={async (e) => {
          e.preventDefault();
          if (!feature) return;
          const ok = await form.submit(async () => {
            const r = await put(`/admin/tenants/${orgId}/overrides/${feature}`, {
              enabled, limit_value: limit.trim() === "" ? null : Number(limit), expires_at: until ? `${until}T23:59:59Z` : null, reason,
            });
            return r.ok ? null : r.problem;
          });
          if (ok) { notify({ title: "Exception saved", kind: "success" }); setMessage(`The exception for ${featureLabel(feature)} is saved.`); setReason(""); void list.reload(); }
        }}
      >
        <Select label="Feature" isRequired value={feature} onChange={(k) => setFeature(k ? String(k) : null)} options={features.map((f) => ({ id: f, label: featureLabel(f) }))} />
        <Checkbox label="Allow this feature" isSelected={enabled} onChange={setEnabled} />
        <TextField id="field-limit_value" label="Limit per month" type="number" inputMode="numeric" description="Leave empty for no limit. Seats and pages per scan are totals, not monthly." value={limit} onChange={setLimit} />
        <TextField id="field-expires_at" label="Ends on (optional)" type="date" value={until} onChange={setUntil} error={form.fieldError("expires_at")} />
        <TextField id="field-reason" label="Reason" description="Recorded in the audit log, for example “Pilot extension agreed on 12 December”." value={reason} onChange={setReason} isRequired error={form.fieldError("reason")} />
        <Button type="submit" isPending={form.submitting} pendingLabel="Saving exception" isDisabled={!feature}>Save exception</Button>
      </Form>
    </div>
  );
}

export function OverridesDialog({ orgId, orgName }: { orgId: string; orgName: string }) {
  return (
    <DialogTrigger>
      <Button variant="secondary">Exceptions<span className="a11y-sr-only"> for {orgName}</span></Button>
      <Dialog title={`Exceptions for ${orgName}`}><Body orgId={orgId} /></Dialog>
    </DialogTrigger>
  );
}
