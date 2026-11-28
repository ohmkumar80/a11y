"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, Select, StatusMessage } from "@a11y/ui";
import { post } from "@/lib/api";
import { useFlags } from "@/lib/flags";
import { useAuth } from "./AuthProvider";

const EDITIONS = [
  { id: "WCAG", label: "WCAG edition" }, { id: "508", label: "Revised Section 508 edition" },
  { id: "EU", label: "EU edition (EN 301 549)" }, { id: "INT", label: "International edition" },
];

/** Starts (or reopens) the VPAT draft for this scan. Only administrators sign off, so only they see the button. */
export function VpatStart({ scanId, standard }: { scanId: string; standard: string }) {
  const { user } = useAuth();
  const flags = useFlags();
  const router = useRouter();
  const [edition, setEdition] = useState("WCAG");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (user?.role !== "COMPANY_ADMIN" || !flags.vpat) return null;
  return (
    <section aria-labelledby="vpat" className="flex max-w-xl flex-col gap-3">
      <h2 id="vpat" className="text-xl font-bold">Accessibility Conformance Report (VPAT)</h2>
      <p className="text-fg-muted">
        We prefill a draft from this scan. Automated tests can show where a criterion fails; they can never show that one is met, so every other criterion starts as
        &ldquo;Not Evaluated&rdquo;. You review and complete it, then sign it off before it can be exported.
      </p>
      <Select label="Edition" value={edition} onChange={(k) => setEdition(String(k))} options={EDITIONS} />
      <div>
        <Button isPending={busy} pendingLabel="Opening VPAT draft" onPress={async () => {
          setBusy(true); setError(null);
          const r = await post<{ id: string }>(`/scans/${scanId}/vpat`, { standard, edition });
          setBusy(false);
          if (r.ok) router.push(`/workspace/vpat?id=${r.data.id}`); else setError(r.problem.detail);
        }}>Open VPAT draft</Button>
      </div>
      {error && <StatusMessage>{error}</StatusMessage>}
    </section>
  );
}
