"use client";

import NextLink from "next/link";
import { useState } from "react";
import { Form, Button, ErrorSummary, StatusMessage, TextField } from "@a11y/ui";
import { Page } from "@/components/Page";
import { useForm } from "@/components/useForm";
import { post } from "@/lib/api";

export default function SignupPage() {
  const form = useForm();
  const [sent, setSent] = useState<string | null>(null);
  const [org, setOrg] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  if (sent) {
    return (
      <Page title="Check your email" narrow>
        <StatusMessage kind="success">
          If we can create the account, we have sent a confirmation link to {sent}. It works for 24 hours.
        </StatusMessage>
        <p><NextLink href="/login" className="underline">Back to log in</NextLink></p>
      </Page>
    );
  }
  return (
    <Page title="Create your account" intro="Start a 14-day trial. No card needed." narrow>
      <ErrorSummary errors={form.errors} />
      <Form
        className="flex flex-col gap-4"
        onSubmit={async (e) => {
          e.preventDefault();
          const ok = await form.submit(async () => {
            const r = await post("/auth/signup", { organization_name: org, email, password });
            return r.ok ? null : r.problem;
          });
          if (ok) setSent(email);
        }}
      >
        <TextField id="field-organization_name" label="Organisation name" autoComplete="organization" value={org} onChange={setOrg} isRequired error={form.fieldError("organization_name")} />
        <TextField id="field-email" label="Work email" type="email" autoComplete="email" value={email} onChange={setEmail} isRequired error={form.fieldError("email")} />
        <TextField
          id="field-password"
          label="Password"
          type="password"
          autoComplete="new-password"
          description="At least 12 characters. A passphrase of a few words works well. You can paste from a password manager."
          value={password}
          onChange={setPassword}
          isRequired
          error={form.fieldError("password")}
        />
        <Button type="submit" isPending={form.submitting} pendingLabel="Creating account">Create account</Button>
      </Form>
      <p>Already have an account? <NextLink href="/login" className="underline">Log in</NextLink></p>
    </Page>
  );
}
