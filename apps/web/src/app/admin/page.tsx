"use client";

import { Tabs, StatusMessage } from "@a11y/ui";
import { useCallback, useEffect, useState } from "react";
import { get } from "@/lib/api";
import { SecurityTab } from "@/components/admin/SecurityTab";
import { AiTab } from "@/components/admin/AiTab";
import { CouponsTab } from "@/components/admin/CouponsTab";
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

export default function AdminPage() {
  const [refresh, setRefresh] = useState(0);
  const bump = useCallback(() => setRefresh((n) => n + 1), []);
  return (
    <RequireAuth requiredRole="SUPER_ADMIN">
      {() => (
        <Page title="Admin" intro="Manage organisations, plans, coupons and platform settings. Every change is audit-logged.">
          <MfaOffBanner refresh={refresh} />
          <Tabs
            label="Admin sections"
            items={[
              { id: "tenants", label: "Organisations", content: <TenantsTab /> },
              { id: "plans", label: "Plans", content: <PlansTab /> },
              { id: "coupons", label: "Coupons", content: <CouponsTab /> },
              { id: "ai", label: "AI", content: <AiTab /> },
              { id: "security", label: "Security", content: <SecurityTab onChanged={bump} /> },
              { id: "settings", label: "Settings", content: <SettingsTab /> },
            ]}
          />
        </Page>
      )}
    </RequireAuth>
  );
}
