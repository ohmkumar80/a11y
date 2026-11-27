"use client";

import NextLink from "next/link";
import { useState } from "react";
import { Button, ErrorSummary, Form, Meter, StatusMessage, TextField, notify } from "@a11y/ui";
import { post } from "@/lib/api";
import { STATUS_LABEL, daysLeft, discountText, featureLabel, formatDate, type Subscription } from "@/lib/billing";
import { useForm } from "./useForm";

function Usage({ label, used, limit, unit, custom }: { label: string; used: number; limit: number | null; unit: string; custom?: boolean }) {
  if (limit === null) return <p><span className="font-semibold">{label}:</span> {used} used. {custom ? "No limit for your organisation." : "Unlimited on your plan."}</p>;
  if (limit === 0) return <p><span className="font-semibold">{label}:</span> not included in your plan.</p>;
  return (
    <div className="flex flex-col gap-1">
      <Meter label={label} value={Math.min(used, limit)} maxValue={limit} valueText={`${used} of ${limit}${unit}`} />
      {custom && <p className="text-sm">A custom limit has been set for your organisation.</p>}
    </div>
  );
}

export function PlanPanel({ sub, onChanged }: { sub: Subscription; onChanged: () => void }) {
  const [code, setCode] = useState("");
  const form = useForm();
  const locked = sub.status === "LOCKED_READ_ONLY";

  return (
    <section aria-labelledby="plan" className="flex flex-col gap-4">
      <h2 id="plan" className="text-xl font-bold">Plan and usage</h2>

      <dl className="grid max-w-xl grid-cols-[max-content_1fr] gap-x-6 gap-y-1">
        <dt className="font-semibold">Plan</dt>
        <dd>{sub.plan.name}</dd>
        <dt className="font-semibold">Status</dt>
        <dd>{STATUS_LABEL[sub.status]}</dd>
        {sub.status === "TRIALING" && sub.trial_ends_at && (
          <>
            <dt className="font-semibold">Trial ends</dt>
            <dd>{formatDate(sub.trial_ends_at)} ({daysLeft(sub.trial_ends_at)} {daysLeft(sub.trial_ends_at) === 1 ? "day" : "days"} left)</dd>
          </>
        )}
        {sub.coupon && (
          <>
            <dt className="font-semibold">Coupon</dt>
            <dd>{sub.coupon.code}: {discountText(sub.coupon)}</dd>
          </>
        )}
      </dl>

      {locked && (
        <StatusMessage>
          Your trial has ended, so this organisation is read-only. You can still view past results.{" "}
          <NextLink href="/help" className="underline">Contact us to choose a plan</NextLink>.
        </StatusMessage>
      )}

      <div className="flex max-w-xl flex-col gap-4">
        <Usage label="Seats" used={sub.seats.used} limit={sub.seats.limit} unit=" seats" />
        {sub.quotas.map((q) => (
          <Usage key={q.feature} label={featureLabel(q.feature)} used={q.used} limit={q.enabled ? q.limit : 0} unit="" custom={q.custom} />
        ))}
      </div>

      <p>
        Need a different plan or more seats? <NextLink href="/help" className="underline">Contact us</NextLink>. We assign plans manually for now.
      </p>

      {!sub.coupon && !locked && (
        <div className="flex max-w-md flex-col gap-3">
          <h3 className="text-lg font-bold">Have a coupon?</h3>
          <ErrorSummary errors={form.errors} />
          <Form
            className="flex flex-col gap-4"
            onSubmit={async (e) => {
              e.preventDefault();
              const ok = await form.submit(async () => {
                const r = await post("/org/coupon", { code });
                return r.ok ? null : r.problem;
              });
              if (ok) {
                notify({ title: "Coupon applied", description: "Your discount is on your account.", kind: "success" });
                setCode("");
                onChanged();
              }
            }}
          >
            <TextField id="field-code" label="Coupon code" autoComplete="off" value={code} onChange={setCode} isRequired error={form.fieldError("code")} />
            <Button type="submit" isPending={form.submitting} pendingLabel="Applying coupon">Apply coupon</Button>
          </Form>
        </div>
      )}
    </section>
  );
}
