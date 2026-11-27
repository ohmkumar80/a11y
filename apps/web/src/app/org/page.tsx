"use client";

import { useCallback, useEffect, useState } from "react";
import { Button, ErrorSummary, Form, Select, Table, TextField, notify } from "@a11y/ui";
import { Page } from "@/components/Page";
import { RequireAuth } from "@/components/RequireAuth";
import { useForm } from "@/components/useForm";
import NextLink from "next/link";
import { SecurityPanel } from "@/components/mfa/SecurityPanel";
import { PlanPanel } from "@/components/PlanPanel";
import { get, post, type User } from "@/lib/api";
import type { Subscription } from "@/lib/billing";

const ROLE_LABEL = { COMPANY_ADMIN: "Administrator", STANDARD_USER: "Member", SUPER_ADMIN: "Super admin" } as const;

function Team({ onInvited }: { onInvited: () => void }) {
  const [users, setUsers] = useState<User[] | null>(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<string>("STANDARD_USER");
  const form = useForm();

  const load = useCallback(async () => {
    const r = await get<User[]>("/org/users");
    if (r.ok) setUsers(r.data);
  }, []);
  useEffect(() => { void load(); }, [load]);

  return (
    <>
      <section aria-labelledby="team" className="flex flex-col gap-3">
        <h2 id="team" className="text-xl font-bold">Team</h2>
        <p role="status">{users ? `${users.length} ${users.length === 1 ? "person" : "people"} in your organisation.` : "Loading team."}</p>
        <Table
          label="Team members"
          rows={users ?? []}
          rowKey={(u) => u.id}
          columns={[
            { id: "email", header: "Email", isRowHeader: true, render: (u) => u.email },
            { id: "role", header: "Role", render: (u) => ROLE_LABEL[u.role] },
          ]}
        />
      </section>
      <section aria-labelledby="invite" className="flex max-w-md flex-col gap-3">
        <h2 id="invite" className="text-xl font-bold">Invite someone</h2>
        <ErrorSummary errors={form.errors} />
        <Form
          className="flex flex-col gap-4"
          onSubmit={async (e) => {
            e.preventDefault();
            const ok = await form.submit(async () => { const r = await post("/invites", { email, role }); return r.ok ? null : r.problem; });
            if (ok) {
              notify({ title: "Invitation sent", description: `If ${email} can join, they will get an email.`, kind: "success" });
              setEmail("");
              onInvited();
              void load();
            }
          }}
        >
          <TextField id="field-email" label="Email" type="email" autoComplete="off" value={email} onChange={setEmail} isRequired error={form.fieldError("email")} />
          <Select label="Role" value={role} onChange={(k) => setRole(String(k))} options={[{ id: "STANDARD_USER", label: "Member" }, { id: "COMPANY_ADMIN", label: "Administrator" }]} />
          <Button type="submit" isPending={form.submitting} pendingLabel="Sending invitation">Send invitation</Button>
        </Form>
      </section>
    </>
  );
}

function OrgContent({ name }: { name: string }) {
  const [sub, setSub] = useState<Subscription | null>(null);
  const [failed, setFailed] = useState(false);
  const load = useCallback(async () => {
    const r = await get<Subscription>("/org/subscription");
    if (r.ok) setSub(r.data);
    else setFailed(true);
  }, []);
  useEffect(() => { void load(); }, [load]);
  return (
    <Page title="Organisation" intro={name}>
      {sub ? <PlanPanel sub={sub} onChanged={() => void load()} /> : <p role="status">{failed ? "We could not load your plan. Refresh the page to try again." : "Loading your plan."}</p>}
      <section aria-labelledby="ai" className="flex flex-col gap-2">
        <h2 id="ai" className="text-xl font-bold">AI provider</h2>
        <p>On the Enterprise plan you can use your own OpenAI, Azure OpenAI or DeepSeek keys. <NextLink href="/org/ai" className="underline">Manage AI provider settings</NextLink>.</p>
      </section>
      <section aria-labelledby="security" className="flex flex-col gap-2">
        <h2 id="security" className="text-xl font-bold">Your security</h2>
        <SecurityPanel />
      </section>
      <Team onInvited={() => void load()} />
    </Page>
  );
}

export default function OrgPage() {
  return (
    <RequireAuth requiredRole="COMPANY_ADMIN">
      {(user) => <OrgContent name={user.organization_name} />}
    </RequireAuth>
  );
}
