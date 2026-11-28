"use client";

import { useState } from "react";
import { Button } from "@a11y/ui";
import { post } from "@/lib/api";

interface TestResult { ok: boolean; detail: string; model_id?: string; latency_ms?: number }

/** "Test connection" for one provider. The result is announced politely (role=status) and stays
 *  visible, so nothing depends on a toast the user might miss. */
export function ProviderTest({ path, name, body = {} }: { path: string; name: string; body?: unknown }) {
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<TestResult | null>(null);
  return (
    <div className="flex flex-col gap-1">
      <div>
        <Button variant="secondary" isPending={busy} pendingLabel={`Testing ${name}`} onPress={async () => {
          setBusy(true); setRes(null);
          const r = await post<TestResult>(path, body);
          setRes(r.ok ? r.data : { ok: false, detail: r.problem.detail });
          setBusy(false);
        }}>Test connection<span className="a11y-sr-only"> for {name}</span></Button>
      </div>
      <p role="status" className={res && !res.ok ? "font-semibold text-danger" : ""}>
        {res && (res.ok ? `✓ Connected${res.latency_ms ? ` in ${res.latency_ms} ms` : ""}.` : `⚠ Failed: ${res.detail}`)}
      </p>
    </div>
  );
}
