/** The admin sections, in navigation order. The side navigation and the admin page both read this list. */
export const ADMIN_TABS = [
  { id: "overview", label: "Overview", group: "Platform" },
  { id: "tenants", label: "Organisations", group: "Platform" },
  { id: "plans", label: "Plans", group: "Platform" },
  { id: "coupons", label: "Coupons", group: "Platform" },
  { id: "ai", label: "AI", group: "Product" },
  { id: "documents", label: "Documents", group: "Product" },
  { id: "reviews", label: "Reviews", group: "Product" },
  { id: "emails", label: "Emails", group: "Product" },
  { id: "ops", label: "Operations", group: "System" },
  { id: "security", label: "Security", group: "System" },
  { id: "settings", label: "Settings", group: "System" },
] as const;
export type AdminTabId = (typeof ADMIN_TABS)[number]["id"];
