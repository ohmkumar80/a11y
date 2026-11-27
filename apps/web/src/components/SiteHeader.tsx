"use client";

import NextLink from "next/link";
import { usePathname } from "next/navigation";
import { Button } from "@a11y/ui";
import { useAuth } from "./AuthProvider";

const navLink = "inline-flex min-h-11 items-center px-3 underline-offset-4 hover:underline aria-[current=page]:font-bold aria-[current=page]:underline";

export function SiteHeader() {
  const { user, logout } = useAuth();
  const path = usePathname();
  const cur = (href: string) => (path === href || path.startsWith(`${href}/`) ? ("page" as const) : undefined);

  // Header is NOT sticky: nothing may obscure focused content (SC 2.4.11).
  return (
    <header className="border-b-2 border-border-subtle bg-bg">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2 px-4 py-2">
        <NextLink href="/" className="inline-flex min-h-11 items-center text-lg font-bold">a11y</NextLink>
        <nav aria-label="Main" className="flex flex-wrap items-center">
          {user?.role === "SUPER_ADMIN" && <NextLink href="/admin" aria-current={cur("/admin")} className={navLink}>Admin</NextLink>}
          {user && <NextLink href="/workspace" aria-current={cur("/workspace")} className={navLink}>Workspace</NextLink>}
          {user?.role === "COMPANY_ADMIN" && <NextLink href="/org" aria-current={cur("/org")} className={navLink}>Organisation</NextLink>}
          {/* Help is always last in the nav on every page (SC 3.2.6 Consistent Help). */}
          <NextLink href="/help" aria-current={cur("/help")} className={navLink}>Help</NextLink>
          {user === null && <NextLink href="/login" aria-current={cur("/login")} className={navLink}>Log in</NextLink>}
          {user && (
            <Button variant="secondary" onPress={() => void logout().then(() => (location.href = "/login"))}>
              Log out
            </Button>
          )}
        </nav>
      </div>
    </header>
  );
}

export function SiteFooter() {
  return (
    <footer className="mt-12 border-t-2 border-border-subtle bg-bg-subtle">
      <nav aria-label="Footer" className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 px-4 py-4">
        <NextLink href="/accessibility" className={navLink}>Accessibility statement</NextLink>
        <NextLink href="/help" className={navLink}>Help and contact</NextLink>
      </nav>
    </footer>
  );
}
