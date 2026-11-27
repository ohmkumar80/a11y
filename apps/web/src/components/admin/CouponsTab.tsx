"use client";

import { useState } from "react";
import { Button, ErrorSummary, Form, Table, TextArea, notify } from "@a11y/ui";
import { patch, post } from "@/lib/api";
import { discountText, formatDate } from "@/lib/billing";
import { useApi } from "@/lib/useApi";
import { useForm } from "../useForm";
import { SchemaForm, prepare, type Json, type Schema } from "./SchemaForm";

interface Coupon { id: string; code: string; discount_type: "PERCENTAGE" | "FIXED_INR"; discount_value: number; valid_until: string | null; max_redemptions: number | null; current_redemptions: number; applicable_plan_ids: string[]; is_active: boolean }

const SCHEMA: Schema = {
  type: "object",
  properties: {
    code: { type: "string", description: "Letters, digits, hyphen and underscore. Stored in upper case.", maxLength: 64 },
    discount_type: { type: "string", enum: ["PERCENTAGE", "FIXED_INR"] },
    discount_value: { type: "integer", minimum: 1, description: "A percentage (1 to 100), or paise for a fixed amount: 50000 means ₹500." },
    valid_until: { anyOf: [{ type: "string", format: "date" }, { type: "null" }], description: "Last day the code works." },
    max_redemptions: { anyOf: [{ type: "integer", minimum: 1 }, { type: "null" }], description: "Leave empty for no limit." },
    applicable_plan_ids: { type: "array", items: { type: "string" }, description: "Plan ids this coupon works on. Leave empty for all plans." },
  },
};
interface Campaign { campaign: string; codes: number; redeemed: number; active: number; created_at: string; valid_until: string | null }
const BATCH_SCHEMA: Schema = {
  type: "object",
  properties: {
    campaign: { type: "string", description: "A name for this batch, for example “Partner webinar”. It must be new.", maxLength: 60 },
    prefix: { type: "string", description: "Capital letters and digits at the start of every code, for example WEBINAR.", maxLength: 12 },
    count: { type: "integer", minimum: 1, description: "How many codes to make (up to 500)." },
    discount_type: { type: "string", enum: ["PERCENTAGE", "FIXED_INR"] },
    discount_value: { type: "integer", minimum: 1, description: "A percentage (1 to 100), or paise for a fixed amount: 50000 means ₹500." },
    max_redemptions: { type: "integer", minimum: 1, description: "Uses allowed per code. 1 makes each code single-use." },
    valid_until: { anyOf: [{ type: "string", format: "date" }, { type: "null" }], description: "Last day the codes work." },
    applicable_plan_ids: { type: "array", items: { type: "string" }, description: "Plan ids the codes work on. Leave empty for all plans." },
  },
};
const BATCH_BLANK: Json = { campaign: "", prefix: "", count: 25, discount_type: "PERCENTAGE", discount_value: 20, max_redemptions: 1, valid_until: null, applicable_plan_ids: [] };
const BLANK: Json = { code: "", discount_type: "PERCENTAGE", discount_value: 10, valid_until: null, max_redemptions: null, applicable_plan_ids: [] };

export function CouponsTab() {
  const coupons = useApi<Coupon[]>("/admin/coupons");
  const campaigns = useApi<Campaign[]>("/admin/coupons-campaigns");
  const [batch, setBatch] = useState<Json>(BATCH_BLANK);
  const [made, setMade] = useState<{ campaign: string; codes: string[] } | null>(null);
  const [campMessage, setCampMessage] = useState("");
  const batchForm = useForm();
  const [value, setValue] = useState<Json>(BLANK);
  const form = useForm();
  const toggle = async (c: Coupon) => {
    const r = await patch(`/admin/coupons/${c.id}`, { is_active: !c.is_active });
    if (r.ok) { notify({ title: `Coupon ${c.code} ${c.is_active ? "deactivated" : "activated"}`, kind: "success" }); void coupons.reload(); }
    else notify({ title: "Could not change the coupon", description: r.problem.detail, kind: "error" });
  };

  return (
    <div className="flex flex-col gap-8">
      <section aria-labelledby="coupons" className="flex flex-col gap-3">
        <h2 id="coupons" className="text-xl font-bold">Coupons</h2>
        <Table<Coupon>
          label="Coupons"
          rows={coupons.data ?? []}
          rowKey={(c) => c.id}
          emptyText={coupons.data ? "No coupons yet." : "Loading coupons."}
          columns={[
            { id: "code", header: "Code", isRowHeader: true, render: (c) => c.code },
            { id: "discount", header: "Discount", render: (c) => discountText({ type: c.discount_type, value: c.discount_value }) },
            { id: "used", header: "Redeemed", render: (c) => `${c.current_redemptions}${c.max_redemptions ? ` of ${c.max_redemptions}` : ""}` },
            { id: "until", header: "Valid until", render: (c) => (c.valid_until ? formatDate(c.valid_until) : "No end date") },
            { id: "plans", header: "Plans", render: (c) => (c.applicable_plan_ids.length ? c.applicable_plan_ids.join(", ") : "All") },
            { id: "state", header: "State", render: (c) => (c.is_active ? "Active" : "Inactive") },
            { id: "act", header: "Action", render: (c) => <Button variant="secondary" onPress={() => void toggle(c)}>{c.is_active ? "Deactivate" : "Activate"}<span className="a11y-sr-only"> coupon {c.code}</span></Button> },
          ]}
        />
      </section>

      <section aria-labelledby="new-coupon" className="flex max-w-xl flex-col gap-3">
        <h2 id="new-coupon" className="text-xl font-bold">Create a coupon</h2>
        <ErrorSummary errors={form.errors} />
        <Form
          className="flex flex-col gap-4"
          onSubmit={async (e) => {
            e.preventDefault();
            const body = prepare(value) as Record<string, Json>;
            if (typeof body.valid_until === "string" && body.valid_until) body.valid_until = `${body.valid_until}T23:59:59Z`;
            const ok = await form.submit(async () => {
              const r = await post("/admin/coupons", body);
              return r.ok ? null : r.problem;
            });
            if (ok) { notify({ title: "Coupon created", kind: "success" }); setValue(BLANK); void coupons.reload(); }
          }}
        >
          <SchemaForm schema={SCHEMA} value={value} onChange={setValue} idPrefix="field" />
          <Button type="submit" isPending={form.submitting} pendingLabel="Creating coupon">Create coupon</Button>
        </Form>
      </section>

      <section aria-labelledby="campaigns" className="flex flex-col gap-3">
        <h2 id="campaigns" className="text-xl font-bold">Campaigns (batches of codes)</h2>
        <p role="status">{campMessage}</p>
        <Table<Campaign>
          label="Coupon campaigns"
          rows={campaigns.data ?? []}
          rowKey={(c) => c.campaign}
          emptyText={campaigns.data ? "No campaigns yet." : "Loading campaigns."}
          columns={[
            { id: "n", header: "Campaign", isRowHeader: true, render: (c) => c.campaign },
            { id: "c", header: "Codes", render: (c) => String(c.codes) },
            { id: "r", header: "Redeemed", render: (c) => String(c.redeemed) },
            { id: "a", header: "Still active", render: (c) => String(c.active) },
            { id: "x", header: "Action", render: (c) => c.active > 0 ? (
              <Button variant="secondary" onPress={async () => {
                const r = await post(`/admin/coupons-campaigns/${encodeURIComponent(c.campaign)}/deactivate`);
                setCampMessage(r.ok ? `Every code in “${c.campaign}” is switched off.` : r.problem.detail);
                void campaigns.reload(); void coupons.reload();
              }}>Switch off all codes<span className="a11y-sr-only"> in {c.campaign}</span></Button>
            ) : null },
          ]}
        />
      </section>

      <section aria-labelledby="new-batch" className="flex max-w-xl flex-col gap-3">
        <h2 id="new-batch" className="text-xl font-bold">Create a batch of codes</h2>
        <p className="text-fg-muted">Each code is random, unique and easy to read out (no 0, O, 1 or I). The codes are shown once below; copy or download them before leaving.</p>
        <ErrorSummary errors={batchForm.errors} />
        <Form
          className="flex flex-col gap-4"
          onSubmit={async (e) => {
            e.preventDefault();
            const body = prepare(batch) as Record<string, Json>;
            if (typeof body.valid_until === "string" && body.valid_until) body.valid_until = `${body.valid_until}T23:59:59Z`;
            const ok = await batchForm.submit(async () => {
              const r = await post<{ campaign: string; codes: string[] }>("/admin/coupons/bulk", body);
              if (!r.ok) return r.problem;
              setMade(r.data);
              return null;
            });
            if (ok) { notify({ title: "Codes created", kind: "success" }); setBatch(BATCH_BLANK); void campaigns.reload(); void coupons.reload(); }
          }}
        >
          <SchemaForm schema={BATCH_SCHEMA} value={batch} onChange={setBatch} idPrefix="field" />
          <Button type="submit" isPending={batchForm.submitting} pendingLabel="Creating codes">Create codes</Button>
        </Form>
        {made && (
          <div className="flex flex-col gap-2">
            <TextArea label={`${made.codes.length} codes for “${made.campaign}”`} rows={8} value={made.codes.join("\n")} onChange={() => undefined} isReadOnly />
            <div className="flex flex-wrap gap-3">
              <Button variant="secondary" onPress={async () => { await navigator.clipboard?.writeText(made.codes.join("\n")); notify({ title: "Codes copied", kind: "success" }); }}>Copy all codes</Button>
              <Button variant="secondary" onPress={() => {
                const url = URL.createObjectURL(new Blob([`code\n${made.codes.join("\n")}\n`], { type: "text/csv" }));
                const a = document.createElement("a"); a.href = url; a.download = `${made.campaign.replace(/[^A-Za-z0-9]+/g, "-")}-codes.csv`; a.click(); URL.revokeObjectURL(url);
              }}>Download as CSV</Button>
              <Button variant="secondary" onPress={() => setMade(null)}>I have saved them</Button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
