"use client";

import { useCallback, useEffect, useState } from "react";
import { Button, ErrorSummary, Form, StatusMessage, TextField } from "@a11y/ui";
import type { MfaChallenge } from "@/lib/api";
import { useAuth } from "../AuthProvider";
import { Page } from "../Page";
import { useForm } from "../useForm";
import { EnrolPanel } from "./EnrolPanel";
import { RecoveryCodes } from "./RecoveryCodes";

/** The second step of signing in: enter a code, or enrol first when policy requires it. */
export function SignInSteps({ challenge, onDone, onRestart }: { challenge: MfaChallenge; onDone: () => void; onRestart: () => void }) {
  const { verifyMfa, enrolStart, enrolConfirm } = useAuth();
  const [useRecovery, setUseRecovery] = useState(false);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [expired, setExpired] = useState(false);
  const form = useForm();
  // Each step is a new "page" for a screen-reader user: move focus to its heading (SC 2.4.3).
  useEffect(() => { document.querySelector<HTMLElement>("main h1")?.focus(); }, [useRecovery, codes, expired, challenge.mfa]);

  const start = useCallback(() => enrolStart(challenge.mfa_token), [enrolStart, challenge.mfa_token]);

  if (expired) {
    return (
      <Page title="Sign in again" narrow>
        <StatusMessage>Your sign-in took longer than {Math.round(challenge.expires_in / 60)} minutes, so it was cancelled to keep your account safe.</StatusMessage>
        <div><Button onPress={onRestart}>Start again</Button></div>
      </Page>
    );
  }

  if (codes) {
    return <Page title="Save your recovery codes" narrow><RecoveryCodes codes={codes} onContinue={onDone} /></Page>;
  }

  if (challenge.mfa === "enroll") {
    return (
      <Page title="Set up two-step verification" intro="Your account needs a second step at sign-in. This takes about two minutes." narrow>
        <p className="text-fg-muted">You have {Math.round(challenge.expires_in / 60)} minutes to finish. If it runs out you can start again.</p>
        <EnrolPanel
          start={start}
          confirm={async (c) => {
            const r = await enrolConfirm(challenge.mfa_token, c);
            if ("problem" in r) { if (r.problem.code === "mfa_token_expired") setExpired(true); return r.problem; }
            setCodes(r.codes);
            return null;
          }}
        />
      </Page>
    );
  }

  return (
    <Page title={useRecovery ? "Use a recovery code" : "Enter your verification code"} narrow>
      <p className="text-fg-muted">You have {Math.round(challenge.expires_in / 60)} minutes to finish signing in.</p>
      <ErrorSummary errors={form.errors} />
      <Form
        className="flex flex-col gap-4"
        onSubmit={async (e) => {
          e.preventDefault();
          const ok = await form.submit(async () => {
            const p = await verifyMfa(challenge.mfa_token, useRecovery ? { recovery_code: code } : { code });
            if (p?.code === "mfa_token_expired") setExpired(true);
            return p;
          });
          if (ok) onDone();
        }}
      >
        {useRecovery ? (
          <TextField id="field-recovery_code" label="Recovery code" autoComplete="off" value={code} onChange={setCode} isRequired error={form.fieldError("recovery_code")}
            description="One of the codes you saved when you set up two-step verification. Each works once." />
        ) : (
          <TextField id="field-code" label="6-digit code" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={setCode} isRequired error={form.fieldError("code")}
            description="Open your authenticator app. The code changes every 30 seconds. You can paste it." />
        )}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" isPending={form.submitting} pendingLabel="Checking the code">Verify</Button>
          <Button variant="secondary" onPress={() => { setUseRecovery(!useRecovery); setCode(""); }}>{useRecovery ? "Use my authenticator app instead" : "Use a recovery code instead"}</Button>
        </div>
      </Form>
    </Page>
  );
}
