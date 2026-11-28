"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { DomainsPanel } from "@/components/DomainsPanel";
import { NewScanForm } from "@/components/NewScanForm";
import { Page } from "@/components/Page";
import { RequireAuth } from "@/components/RequireAuth";
import { ScansTable } from "@/components/ScansTable";
import type { User } from "@/lib/api";

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
            {user.role !== "SUPER_ADMIN" && (
              <>
                <NewScanForm canVerify={user.role === "COMPANY_ADMIN"} />
                <ScansTable />
                {user.role === "COMPANY_ADMIN" && <DomainsPanel />}
              </>
            )}
          </Page>
        </>
      )}
    </RequireAuth>
  );
}
