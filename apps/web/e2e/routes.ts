import type { Role } from "./fixtures";

// Every route x every role that can reach it. Add new routes here: CI fails if a route in the
// app is missing (see routes.spec.ts).
export const ROUTES: Array<{ path: string; roles: Role[] }> = [
  { path: "/", roles: ["ANON", "COMPANY_ADMIN"] },
  { path: "/login", roles: ["ANON"] },
  { path: "/login?verified=1", roles: ["ANON"] },
  { path: "/signup", roles: ["ANON"] },
  { path: "/verify-email?token=abc", roles: ["ANON"] },
  { path: "/forgot-password", roles: ["ANON"] },
  { path: "/reset-password?token=abc", roles: ["ANON"] },
  { path: "/accept-invite?token=abc", roles: ["ANON"] },
  { path: "/help", roles: ["ANON", "STANDARD_USER"] },
  { path: "/accessibility", roles: ["ANON"] },
  { path: "/workspace", roles: ["COMPANY_ADMIN", "STANDARD_USER"] },
  { path: "/org", roles: ["COMPANY_ADMIN", "STANDARD_USER"] }, // standard user sees the no-access page
  { path: "/admin", roles: ["SUPER_ADMIN", "COMPANY_ADMIN"] }, // company admin sees the no-access page
  { path: "/does-not-exist", roles: ["ANON"] },
];
