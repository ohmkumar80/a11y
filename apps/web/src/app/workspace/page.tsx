"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Dashboard } from "@/components/Dashboard";
import { Page } from "@/components/Page";
import { RequireAuth } from "@/components/RequireAuth";
import type { User } from "@/lib/api";

function ToAdmin({ user }: { user: User }) {
  // Platform operators have no tenant; their home is /admin.
  const router = useRouter();
  useEffect(() => { if (user.role === "SUPER_ADMIN") router.replace("/admin"); else if (user.role === "REVIEWER") router.replace("/review"); }, [user, router]);
  return null;
}

export default function WorkspacePage() {
  return (
    <RequireAuth>
      {(user) => (
        <>
          <ToAdmin user={user} />
          <Page title="Workspace" intro={`Signed in as ${user.email} · ${user.organization_name}`}>
            {user.role !== "SUPER_ADMIN" && user.role !== "REVIEWER" && <Dashboard user={user} />}
          </Page>
        </>
      )}
    </RequireAuth>
  );
}
