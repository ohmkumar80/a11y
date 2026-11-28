"use client";

import NextLink from "next/link";
import { useState } from "react";
import { Form, Button, ErrorSummary, StatusMessage, TextField } from "@a11y/ui";
import { Page } from "@/components/Page";
import { useForm } from "@/components/useForm";
import { post } from "@/lib/api";

export default function ForgotPasswordPage() {
  const form = useForm();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  return (
    <Page title="Forgot your password?" intro="Enter your email and we will send you a link to choose a new one." narrow>
      <ErrorSummary errors={form.errors} />
      {sent && <StatusMessage kind="success">If an account exists for {email}, we have sent a reset link. It works for 1 hour.</StatusMessage>}
      <Form
        className="flex flex-col gap-4"
        onSubmit={async (e) => {
          e.preventDefault();
          if (await form.submit(async () => { const r = await post("/auth/password-reset/request", { email }); return r.ok ? null : r.problem; })) setSent(true);
        }}
      >
        <TextField id="field-email" label="Email" type="email" autoComplete="email" value={email} onChange={setEmail} isRequired error={form.fieldError("email")} />
        <Button type="submit" isPending={form.submitting} pendingLabel="Sending">Send reset link</Button>
      </Form>
      <p><NextLink href="/login" className="underline">Back to log in</NextLink></p>
    </Page>
  );
}
