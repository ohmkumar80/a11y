"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Form, Button, ErrorSummary, TextField } from "@a11y/ui";
import { Page } from "@/components/Page";
import { useForm } from "@/components/useForm";
import { get, post } from "@/lib/api";

function Accept() {
  const token = useSearchParams().get("token") ?? "";
  const router = useRouter();
  const form = useForm();
  const [invite, setInvite] = useState<{ email: string; organization_name: string } | "bad" | null>(null);
  const [password, setPassword] = useState("");

  useEffect(() => {
    let ignore = false;
    get<{ email: string; organization_name: string }>(`/invites/${encodeURIComponent(token)}`).then((r) => !ignore && setInvite(r.ok ? r.data : "bad"));
    return () => { ignore = true; };
  }, [token]);

  if (invite === "bad") return <Page title="This invitation does not work" intro="It may have expired or already been used. Ask your administrator to send a new one." narrow />;
  if (!invite) return <Page title="Loading your invitation" narrow><p role="status">Please wait.</p></Page>;
  return (
    <Page title={`Join ${invite.organization_name}`} intro="Choose a password to finish setting up your account." narrow>
      <ErrorSummary errors={form.errors} />
      <Form
        className="flex flex-col gap-4"
        onSubmit={async (e) => {
          e.preventDefault();
          const ok = await form.submit(async () => { const r = await post("/invites/accept", { token, password }); return r.ok ? null : r.problem; });
          if (ok) router.push("/login?verified=1");
        }}
      >
        {/* Pre-filled from the invite: users never retype what we already know (SC 3.3.7). */}
        <TextField label="Email" type="email" autoComplete="username" value={invite.email} isReadOnly />
        <TextField id="field-password" label="Password" type="password" autoComplete="new-password" description="At least 12 characters. Pasting is fine." value={password} onChange={setPassword} isRequired error={form.fieldError("password")} />
        <Button type="submit" isPending={form.submitting} pendingLabel="Creating account">Create account</Button>
      </Form>
    </Page>
  );
}

export default function AcceptInvitePage() {
  return <Suspense><Accept /></Suspense>;
}
