"use client";

import { useCallback, useState } from "react";
import { Button, ErrorSummary, Form, StatusMessage, TextField, notify } from "@a11y/ui";
import { post } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import { useAuth } from "../AuthProvider";
import { useForm } from "../useForm";
import { EnrolPanel } from "./EnrolPanel";
import { RecoveryCodes } from "./RecoveryCodes";

interface Status { enabled: boolean; mode: "required" | "optional" | "off"; required: boolean; recovery_codes_left: number; available: boolean }

/** Two-step verification for the person who is signed in (administrators). */
export function SecurityPanel() {
  const status = useApi<Status>("/auth/mfa/status");
  const { patchUser } = useAuth();
  const [stage, setStage] = useState<"idle" | "enrol" | "codes" | "regen" | "disable">("idle");
  const [codes, setCodes] = useState<string[]>([]);
  const [code, setCode] = useState("");
  const form = useForm();
  const s = status.data;

  const start = useCallback(async () => {
    const r = await post<{ key: string; otpauth_uri: string; issuer: string; account: string }>("/auth/mfa/setup/start");
    return r.ok ? { info: r.data } : { problem: r.problem };
  }, []);

  if (!s) return <p role="status">Loading your security settings.</p>;
  if (!s.available) return <p>Two-step verification is available to administrators.</p>;

  const finish = async () => { setStage("idle"); setCode(""); await status.reload(); };

  return (
    <div className="flex max-w-xl flex-col gap-4">
      <p>
        <span className="font-semibold">Two-step verification: {s.enabled ? "On" : "Off"}.</span>{" "}
        {s.mode === "required" && "Your organisation requires it."}
        {s.mode === "optional" && !s.enabled && "It is optional for you. We recommend turning it on."}
        {s.mode === "off" && "Sign-in is not currently asking for a code."}
        {s.enabled && ` ${s.recovery_codes_left} recovery ${s.recovery_codes_left === 1 ? "code is" : "codes are"} left.`}
      </p>

      {stage === "idle" && !s.enabled && s.mode !== "required" && <div><Button onPress={() => setStage("enrol")}>Set up two-step verification</Button></div>}
      {stage === "idle" && !s.enabled && s.mode === "required" && <StatusMessage>You will be asked to set it up the next time you sign in.</StatusMessage>}

      {stage === "enrol" && (
        <EnrolPanel start={start} confirm={async (c) => {
          const r = await post<{ recovery_codes: string[] }>("/auth/mfa/setup/confirm", { code: c });
          if (!r.ok) return r.problem;
          patchUser({ mfa_enabled: true });
          setCodes(r.data.recovery_codes);
          setStage("codes");
          return null;
        }} />
      )}
      {stage === "codes" && <RecoveryCodes codes={codes} onContinue={() => void finish()} />}

      {stage === "idle" && s.enabled && (
        <div className="flex flex-wrap gap-3">
          <Button variant="secondary" onPress={() => setStage("regen")}>Get new recovery codes</Button>
          {!s.required && <Button variant="secondary" onPress={() => setStage("disable")}>Turn off two-step verification</Button>}
        </div>
      )}

      {(stage === "regen" || stage === "disable") && (
        <>
          <ErrorSummary errors={form.errors} />
          <Form className="flex flex-col gap-4" onSubmit={async (e) => {
            e.preventDefault();
            let fresh: string[] | null = null;
            const ok = await form.submit(async () => {
              if (stage === "regen") {
                const r = await post<{ recovery_codes: string[] }>("/auth/mfa/recovery-codes", { code });
                if (r.ok) fresh = r.data.recovery_codes;
                return r.ok ? null : r.problem;
              }
              const r = await post("/auth/mfa/disable", { code });
              return r.ok ? null : r.problem;
            });
            if (!ok) return;
            if (fresh) { setCodes(fresh); setStage("codes"); }
            else { patchUser({ mfa_enabled: false }); notify({ title: "Two-step verification is off", kind: "success" }); await finish(); }
          }}>
            <TextField id="field-code" label="Current 6-digit code" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={setCode} isRequired error={form.fieldError("code")}
              description={stage === "regen" ? "Confirm it is you. Your old recovery codes stop working." : "Confirm it is you before turning it off."} />
            <div className="flex gap-3">
              <Button type="submit" variant={stage === "disable" ? "danger" : "primary"} isPending={form.submitting} pendingLabel="Checking the code">{stage === "regen" ? "Get new codes" : "Turn off"}</Button>
              <Button variant="secondary" onPress={() => { setStage("idle"); setCode(""); }}>Cancel</Button>
            </div>
          </Form>
        </>
      )}
    </div>
  );
}
