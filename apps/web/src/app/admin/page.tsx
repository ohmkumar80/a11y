"use client";

import { Tabs } from "@a11y/ui";
import { AiTab } from "@/components/admin/AiTab";
import { CouponsTab } from "@/components/admin/CouponsTab";
import { PlansTab } from "@/components/admin/PlansTab";
import { SettingsTab } from "@/components/admin/SettingsTab";
import { TenantsTab } from "@/components/admin/TenantsTab";
import { Page } from "@/components/Page";
import { RequireAuth } from "@/components/RequireAuth";

export default function AdminPage() {
  return (
    <RequireAuth requiredRole="SUPER_ADMIN">
      {() => (
        <Page title="Admin" intro="Manage organisations, plans, coupons and platform settings. Every change is audit-logged.">
          <Tabs
            label="Admin sections"
            items={[
              { id: "tenants", label: "Organisations", content: <TenantsTab /> },
              { id: "plans", label: "Plans", content: <PlansTab /> },
              { id: "coupons", label: "Coupons", content: <CouponsTab /> },
              { id: "ai", label: "AI", content: <AiTab /> },
              { id: "settings", label: "Settings", content: <SettingsTab /> },
            ]}
          />
        </Page>
      )}
    </RequireAuth>
  );
}
