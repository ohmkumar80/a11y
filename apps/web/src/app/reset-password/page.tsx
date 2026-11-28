"use client";

import NextLink from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Form, Button, ErrorSummary, TextField } from "@a11y/ui";
import { Page } from "@/components/Page";
import { useForm } from "@/components/useForm";
import { post } from "@/lib/api";

function Reset() {
  const token = useSearchParams().get("token") ?? "";
  const router = useRouter();
  const form = useForm();
  const [password, setPassword] = useState("");
  return (
    <Page title="Choose a new password" narrow>
      <ErrorSummary errors={form.errors} />
      <Form
        className="flex flex-col gap-4"
        onSubmit={async (e) => {
          e.preventDefault();
          const ok = await form.submit(async () => { const r = await post("/auth/password-reset/confirm", { token, password }); return r.ok ? null : r.problem; });
          if (ok) router.push("/login");
        }}
      >
        <TextField id="field-password" label="New password" type="password" autoComplete="new-password" description="At least 12 characters. Pasting is fine." value={password} onChange={setPassword} isRequired error={form.fieldError("password")} />
        <Button type="submit" isPending={form.submitting} pendingLabel="Saving">Save new password</Button>
      </Form>
      <p><NextLink href="/forgot-password" className="underline">Request a new link</NextLink></p>
    </Page>
  );
}

export default function ResetPasswordPage() {
  return <Suspense><Reset /></Suspense>;
}
