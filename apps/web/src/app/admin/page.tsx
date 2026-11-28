"use client";

import { StatusMessage } from "@a11y/ui";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { ADMIN_TABS } from "@/lib/adminTabs";
import { OverviewTab } from "@/components/admin/OverviewTab";
import { get } from "@/lib/api";
import { SecurityTab } from "@/components/admin/SecurityTab";
import { AiTab } from "@/components/admin/AiTab";
import { EmailsTab } from "@/components/admin/EmailsTab";
import { CouponsTab } from "@/components/admin/CouponsTab";
import { DocumentsTab } from "@/components/admin/DocumentsTab";
import { OpsTab } from "@/components/admin/OpsTab";
import { ReviewsTab } from "@/components/admin/ReviewsTab";
import { PlansTab } from "@/components/admin/PlansTab";
import { SettingsTab } from "@/components/admin/SettingsTab";
import { TenantsTab } from "@/components/admin/TenantsTab";
import { Page } from "@/components/Page";
import { RequireAuth } from "@/components/RequireAuth";

/** Shown on every admin screen while two-step verification is off, so nobody forgets it. */
function MfaOffBanner({ refresh }: { refresh: number }) {
  const [mode, setMode] = useState<string | null>(null);
  useEffect(() => { void get<{ super_admin: string }>("/admin/security/mfa").then((r) => setMode(r.ok ? r.data.super_admin : null)); }, [refresh]);
  if (mode !== "off") return null;
  return (
    <StatusMessage>
      <strong>Two-step verification is OFF for platform administrators.</strong> This is meant for development only. Switch it on in the Security tab before real use.
    </StatusMessage>
  );
}

function Panels() {
  const [refresh, setRefresh] = useState(0);
  const bump = useCallback(() => setRefresh((n) => n + 1), []);
  const requested = useSearchParams().get("tab");
  const tab = ADMIN_TABS.find((t) => t.id === requested) ?? ADMIN_TABS[0];
  const panel = useRef<HTMLDivElement>(null);
  const first = useRef(true);
  // Choosing another area in the side navigation moves focus to the new content, so keyboard and screen-reader users land on it.
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    panel.current?.focus();
  }, [tab.id]);

  const content: Record<string, ReactNode> = {
    overview: <OverviewTab />,
    tenants: <TenantsTab />,
    plans: <PlansTab />,
    coupons: <CouponsTab />,
    ai: <AiTab />,
    documents: <DocumentsTab />,
    reviews: <ReviewsTab />,
    emails: <EmailsTab />,
    ops: <OpsTab />,
    security: <SecurityTab onChanged={bump} />,
    settings: <SettingsTab />,
  };
  return (
    <>
      <MfaOffBanner refresh={refresh} />
      <div ref={panel} tabIndex={-1} role="group" aria-label={`${tab.label} area`} className="flex flex-col gap-6 outline-none">
        <p className="a11y-kicker">Admin · {tab.label}</p>
        {content[tab.id]}
      </div>
    </>
  );
}

export default function AdminPage() {
  return (
    <RequireAuth requiredRole="SUPER_ADMIN">
      {() => (
        <Page title="Admin" intro="Manage organisations, plans, coupons and platform settings. Every change is audit-logged.">
          <Suspense><Panels /></Suspense>
        </Page>
      )}
    </RequireAuth>
  );
}
