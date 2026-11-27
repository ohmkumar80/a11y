"use client";

import { useState } from "react";
import { Button, ErrorSummary, Form, Table, notify } from "@a11y/ui";
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
const BLANK: Json = { code: "", discount_type: "PERCENTAGE", discount_value: 10, valid_until: null, max_redemptions: null, applicable_plan_ids: [] };

export function CouponsTab() {
  const coupons = useApi<Coupon[]>("/admin/coupons");
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
    </div>
  );
}
