"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import NextLink from "next/link";
import { DomainsPanel } from "@/components/DomainsPanel";
import { NewScanForm } from "@/components/NewScanForm";
import { Page } from "@/components/Page";
import { RequireAuth } from "@/components/RequireAuth";
import { ScansTable } from "@/components/ScansTable";
import type { User } from "@/lib/api";
import { useFlags } from "@/lib/flags";

function ToAdmin({ user }: { user: User }) {
  // Platform operators have no tenant; their home is /admin.
  const router = useRouter();
  useEffect(() => { if (user.role === "SUPER_ADMIN") router.replace("/admin"); }, [user, router]);
  return null;
}

function DocumentsLink() {
  const flags = useFlags();
  if (!flags.documents) return null;
  return (
    <section aria-labelledby="docs-link" className="flex max-w-2xl flex-col gap-2">
      <h2 id="docs-link" className="text-xl font-bold">Documents</h2>
      <p>Check PDF, Word, PowerPoint and EPUB files, not only web pages. <NextLink href="/workspace/documents" className="underline">Go to your documents</NextLink>.</p>
    </section>
  );
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
                <DocumentsLink />
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
