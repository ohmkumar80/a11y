"use client";

import NextLink from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Form, Button, ErrorSummary, StatusMessage, TextField } from "@a11y/ui";
import { useAuth } from "@/components/AuthProvider";
import { SignInSteps } from "@/components/mfa/SignInSteps";
import type { MfaChallenge } from "@/lib/api";
import { Page } from "@/components/Page";
import { useForm } from "@/components/useForm";

function LoginForm() {
  const { login } = useAuth();
  const router = useRouter();
  const verified = useSearchParams().get("verified") === "1";
  const form = useForm();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [challenge, setChallenge] = useState<MfaChallenge | null>(null);

  if (challenge) {
    return <SignInSteps challenge={challenge} onDone={() => router.push("/workspace")} onRestart={() => { setChallenge(null); setPassword(""); }} />;
  }

  return (
    <Page title="Log in" narrow>
      {verified && <StatusMessage kind="success">Your email address is confirmed. Log in to continue.</StatusMessage>}
      <ErrorSummary errors={form.errors} />
      <Form
        className="flex flex-col gap-4"
        onSubmit={async (e) => {
          e.preventDefault();
          let next: MfaChallenge | null = null;
          const ok = await form.submit(async () => {
            const r = await login(email, password);
            if (r.kind === "problem") return r.problem;
            if (r.kind === "mfa") next = r.challenge;
            return null;
          });
          if (!ok) return;
          if (next) { setPassword(""); setChallenge(next); } else router.push("/workspace");
        }}
      >
        <TextField id="field-email" label="Email" type="email" autoComplete="username" value={email} onChange={setEmail} isRequired error={form.fieldError("email")} />
        {/* Paste and password managers are allowed (SC 3.3.8). */}
        <TextField id="field-password" label="Password" type="password" autoComplete="current-password" value={password} onChange={setPassword} isRequired error={form.fieldError("password")} />
        <Button type="submit" isPending={form.submitting} pendingLabel="Logging in">Log in</Button>
      </Form>
      <p><NextLink href="/forgot-password" className="inline-block min-h-6 underline">Forgot your password?</NextLink></p>
      <p>New here? <NextLink href="/signup" className="underline">Create an account</NextLink></p>
    </Page>
  );
}

export default function LoginPage() {
  return <Suspense><LoginForm /></Suspense>;
}
