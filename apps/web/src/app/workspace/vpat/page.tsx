"use client";

import NextLink from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { Button, Checkbox, ErrorSummary, Form, Select, StatusMessage, Table, Tabs, TextArea, TextField, notify } from "@a11y/ui";
import { useAuth } from "@/components/AuthProvider";
import { Page } from "@/components/Page";
import { ReportsPanel } from "@/components/ReportsPanel";
import { RequireAuth } from "@/components/RequireAuth";
import { useForm } from "@/components/useForm";
import { patch, post } from "@/lib/api";
import { formatDate } from "@/lib/billing";
import type { Conformance, Vpat, VpatCriterion } from "@/lib/reports";
import { useApi } from "@/lib/useApi";

type Edit = { conformance?: Conformance; remarks?: string };
const SOURCE: Record<VpatCriterion["source"], string> = { automated: "Set from automated tests", manual: "Edited by a person", default: "Default" };

function evidence(c: VpatCriterion) {
  if (c.failures) return `Automated: ${c.failures} ${c.failures === 1 ? "failure" : "failures"} on ${c.failing_pages} of ${c.scanned_pages} ${c.scanned_pages === 1 ? "page" : "pages"}.${c.review_items ? ` ${c.review_items} to review.` : ""}`;
  if (c.automated_check_exists) return `Automated tests found no issue${c.review_items ? `; ${c.review_items} to review` : ""}. A person must still evaluate it.`;
  return "No automated test exists for this criterion.";
}

function Editor({ id }: { id: string }) {
  const { user } = useAuth();
  const canEdit = user?.role === "COMPANY_ADMIN";
  const { data: vpat, reload } = useApi<Vpat>(`/vpats/${id}`);
  const [edits, setEdits] = useState<Record<string, Edit>>({});
  const [product, setProduct] = useState<Record<string, string>>({});
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [confirm, setConfirm] = useState(false);
  const save = useForm();
  const sign = useForm();
  useEffect(() => { if (vpat) setProduct(vpat.product); }, [vpat]);

  const dirty = Object.keys(edits).length > 0 || (vpat ? JSON.stringify(product) !== JSON.stringify(vpat.product) : false);
  const rows = useMemo(() => (vpat?.criteria ?? []).map((c) => ({ ...c, ...edits[c.id] })), [vpat, edits]);
  if (!vpat) return <p role="status">Loading the VPAT.</p>;
  const locked = vpat.status === "SIGNED_OFF";
  const editable = canEdit && !locked;
  const set = (cid: string, e: Edit) => setEdits((p) => ({ ...p, [cid]: { ...p[cid], ...e } }));

  async function saveAll(): Promise<boolean> {
    return save.submit(async () => {
      const r = await patch(`/vpats/${id}`, {
        product,
        criteria: Object.entries(edits).map(([cid, e]) => ({ id: cid, ...e })),
      });
      if (!r.ok) return { ...r.problem, field: undefined };
      setEdits({});
      await reload();
      return null;
    });
  }

  const tableFor = (level: string) => (
    <Table<VpatCriterion>
      label={`Success criteria, level ${level}`}
      rows={rows.filter((r) => r.level === level)}
      rowKey={(r) => r.id}
      columns={[
        { id: "c", header: "Criterion", isRowHeader: true, render: (r) => `${r.clause} ${r.name}` },
        { id: "e", header: "Automated evidence", render: (r) => <span>{evidence(r)} <span className="text-fg-muted">({SOURCE[edits[r.id] ? "manual" : r.source]})</span></span> },
        {
          id: "l", header: "Conformance level",
          render: (r) => editable ? (
            <Select label={`Conformance level for ${r.clause} ${r.name}`} labelHidden value={r.conformance} onChange={(k) => set(r.id, { conformance: String(k) as Conformance })} options={vpat.levels.map((l) => ({ id: l, label: l }))} />
          ) : r.conformance,
        },
        {
          id: "m", header: "Remarks and explanations",
          render: (r) => editable ? (
            <TextArea label={`Remarks for ${r.clause} ${r.name}`} labelHidden rows={3} value={r.remarks} onChange={(v) => set(r.id, { remarks: v })} />
          ) : r.remarks,
        },
      ]}
    />
  );
  const levels = ["A", "AA", "AAA"].filter((l) => vpat.criteria.some((c) => c.level === l));

  return (
    <div className="flex flex-col gap-8">
      <section aria-labelledby="status" className="flex flex-col gap-2">
        <h2 id="status" className="text-xl font-bold">Status</h2>
        <p><span className="font-semibold">{locked ? "Signed off" : "Draft"}.</span>{" "}
          {locked && vpat.signoff ? `Confirmed by ${vpat.signoff.name} (${vpat.signoff.role}) on ${formatDate(vpat.signoff.signed_at)}.` : "It cannot be exported until a person reviews and signs it off."}</p>
        <p>{vpat.not_evaluated} of {vpat.total} criteria are still &ldquo;Not Evaluated&rdquo;. {vpat.not_evaluated > 0 && "The exported document will say that it is incomplete."}</p>
        {vpat.mapping_review === "draft" && <p>The mapping of this standard to criteria has not yet been signed off by an accessibility expert. The exported document says so.</p>}
        {!canEdit && <StatusMessage>Only an administrator can edit, sign off or export this VPAT. You can read it here.</StatusMessage>}
      </section>

      <section aria-labelledby="product" className="flex max-w-2xl flex-col gap-3">
        <h2 id="product" className="text-xl font-bold">About the product</h2>
        {(["name", "version", "contact"] as const).map((k) => (
          <TextField key={k} label={{ name: "Name of product", version: "Version", contact: "Contact" }[k]} value={product[k] ?? ""} onChange={(v) => setProduct({ ...product, [k]: v })} isReadOnly={!editable} />
        ))}
        {(["description", "notes"] as const).map((k) => (
          <TextArea key={k} label={{ description: "Description", notes: "Notes" }[k]} rows={3} value={product[k] ?? ""} onChange={(v) => setProduct({ ...product, [k]: v })} isReadOnly={!editable} />
        ))}
      </section>

      <section aria-labelledby="criteria" className="flex flex-col gap-3">
        <h2 id="criteria" className="text-xl font-bold">Conformance by criterion</h2>
        <p className="max-w-3xl text-fg-muted">Choose a level for each criterion and explain it. &ldquo;Partially Supports&rdquo; and &ldquo;Does Not Support&rdquo; need remarks. Marking a criterion as supported when automated tests found failures also needs a reason.</p>
        {editable && (
          <>
            <ErrorSummary errors={save.errors} />
            <div><Button isDisabled={!dirty} isPending={save.submitting} pendingLabel="Saving changes" onPress={async () => { if (await saveAll()) notify({ title: "Changes saved", kind: "success" }); }}>Save changes</Button></div>
          </>
        )}
        <Tabs label="Criteria by WCAG level" items={levels.map((l) => ({ id: l, label: `Level ${l}`, content: tableFor(l) }))} />
      </section>

      {vpat.problems.length > 0 && canEdit && !locked && (
        <StatusMessage>
          <p className="font-semibold">Fix these before you can sign off:</p>
          <ul className="list-disc pl-5">{vpat.problems.slice(0, 8).map((p) => <li key={p}>{p}</li>)}</ul>
          {vpat.problems.length > 8 && <p>And {vpat.problems.length - 8} more.</p>}
        </StatusMessage>
      )}

      {editable && (
        <section aria-labelledby="signoff" className="flex max-w-2xl flex-col gap-3">
          <h2 id="signoff" className="text-xl font-bold">Sign off</h2>
          <ErrorSummary errors={sign.errors} />
          <Form className="flex flex-col gap-4" onSubmit={async (e) => {
            e.preventDefault();
            if (dirty && !(await saveAll())) return;
            const ok = await sign.submit(async () => { const r = await post(`/vpats/${id}/signoff`, { name, role, confirm }); return r.ok ? null : r.problem; });
            if (ok) { notify({ title: "VPAT signed off", description: "You can now export it.", kind: "success" }); await reload(); }
          }}>
            <TextField id="field-name" label="Your full name" autoComplete="name" value={name} onChange={setName} isRequired error={sign.fieldError("name")} />
            <TextField id="field-role" label="Your role" autoComplete="organization-title" value={role} onChange={setRole} isRequired error={sign.fieldError("role")} />
            <Checkbox label={vpat.signoff_text} isSelected={confirm} onChange={setConfirm} />
            <div><Button type="submit" isPending={sign.submitting} pendingLabel="Signing off" isDisabled={!confirm}>Sign off this VPAT</Button></div>
          </Form>
        </section>
      )}

      {locked && <ReportsPanel scanId={vpat.scan_id} standard={vpat.standard} vpatId={vpat.id} />}
      {locked && canEdit && (
        <div><Button variant="secondary" onPress={async () => { const r = await post(`/vpats/${id}/reopen`); if (r.ok) { notify({ title: "Reopened", description: "The sign-off was cleared.", kind: "success" }); await reload(); } }}>Reopen to edit</Button></div>
      )}
    </div>
  );
}

function Content() {
  const id = useSearchParams().get("id");
  return id ? <Editor id={id} /> : <StatusMessage>No VPAT was chosen. <NextLink href="/workspace" className="underline">Go to your scans</NextLink>.</StatusMessage>;
}

export default function VpatPage() {
  return (
    <RequireAuth>
      {() => (
        <Page title="VPAT draft" intro="Accessibility Conformance Report. Prefilled from your scan; completed and signed off by a person.">
          <p><NextLink href="/workspace" className="underline">Back to your scans</NextLink></p>
          <Suspense><Content /></Suspense>
        </Page>
      )}
    </RequireAuth>
  );
}
