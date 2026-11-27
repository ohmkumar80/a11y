"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { RequireAuth } from "@/components/RequireAuth";
import type { User } from "@/lib/api";
import { Page } from "@/components/Page";

function ToAdmin({ user }: { user: User }) {
  // Platform operators have no tenant; their home is /admin.
  const router = useRouter();
  useEffect(() => { if (user.role === "SUPER_ADMIN") router.replace("/admin"); }, [user, router]);
  return null;
}

export default function WorkspacePage() {
  return (
    <RequireAuth>
      {(user) => (
        <>
        <ToAdmin user={user} />
        <Page title="Workspace" intro={`Signed in as ${user.email} · ${user.organization_name}`}>
          <section aria-labelledby="scans" className="flex flex-col gap-2">
            <h2 id="scans" className="text-xl font-bold">Scans</h2>
            <p className="text-fg-muted">No scans yet. Website scanning arrives in Phase 1.</p>
          </section>
        </Page>
        </>
      )}
    </RequireAuth>
  );
}
