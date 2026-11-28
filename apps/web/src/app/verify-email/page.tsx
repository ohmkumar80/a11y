"use client";

import NextLink from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { StatusMessage } from "@a11y/ui";
import { Page } from "@/components/Page";
import { post } from "@/lib/api";

function Verify() {
  const token = useSearchParams().get("token");
  const [state, setState] = useState<"working" | "ok" | "bad">("working");
  useEffect(() => {
    if (!token) return setState("bad");
    // Strict mode runs effects twice; the one-time token makes the second call a harmless 400,
    // so only act on the first result.
    let ignore = false;
    post("/auth/verify-email", { token }).then((r) => !ignore && setState(r.ok ? "ok" : "bad"));
    return () => { ignore = true; };
  }, [token]);

  return (
    <Page title={state === "ok" ? "Email confirmed" : state === "bad" ? "This link does not work" : "Confirming your email"} narrow>
      <div role="status">
        {state === "working" && <p>Please wait.</p>}
        {state === "ok" && (
          <StatusMessage kind="success">
            Your email address is confirmed. <NextLink href="/login?verified=1" className="font-semibold underline">Log in</NextLink>
          </StatusMessage>
        )}
        {state === "bad" && (
          <p>This link is invalid or has expired. <NextLink href="/signup" className="underline">Sign up again</NextLink> or <NextLink href="/login" className="underline">log in</NextLink> if you already confirmed.</p>
        )}
      </div>
    </Page>
  );
}

export default function VerifyEmailPage() {
  return <Suspense><Verify /></Suspense>;
}
