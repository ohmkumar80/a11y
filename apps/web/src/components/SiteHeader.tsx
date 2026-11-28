"use client";

import NextLink from "next/link";
import { usePathname } from "next/navigation";
import { Button } from "@a11y/ui";
import { LegalLinks } from "./LegalLinks";
import { NotificationsLink } from "./NotificationsLink";
import { useAuth } from "./AuthProvider";

const navLink =
  "inline-flex min-h-11 items-center rounded-lg px-3 font-medium underline-offset-4 hover:bg-bg-subtle hover:underline aria-[current=page]:bg-accent-subtle aria-[current=page]:font-bold aria-[current=page]:text-accent aria-[current=page]:underline";

/** Decorative mark: the name beside it carries the meaning, so it is hidden from assistive tech. */
export function LogoMark({ className = "size-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" focusable="false" className={className}>
      <rect width="32" height="32" rx="9" className="fill-accent" />
      <path d="M9 16.5l4.5 4.5L23 11.5" fill="none" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" className="stroke-accent-fg" />
    </svg>
  );
}

export function SiteHeader() {
  const { user, logout } = useAuth();
  const path = usePathname();
  const cur = (href: string) => (path === href || path.startsWith(`${href}/`) ? ("page" as const) : undefined);

  // Header is NOT sticky: nothing may obscure focused content (SC 2.4.11).
  return (
    <header className="border-b-2 border-border-subtle bg-bg">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2 px-4 py-2">
        <NextLink href="/" className="inline-flex min-h-11 items-center gap-2.5 rounded-lg pr-2 text-xl font-extrabold tracking-tight">
          <LogoMark />
          a11y
        </NextLink>
        <nav aria-label="Main" className="flex flex-wrap items-center gap-1">
          {user?.role === "SUPER_ADMIN" && <NextLink href="/admin" aria-current={cur("/admin")} className={navLink}>Admin</NextLink>}
          {(user?.role === "REVIEWER" || user?.role === "SUPER_ADMIN") && <NextLink href="/review" aria-current={cur("/review")} className={navLink}>Review queue</NextLink>}
          {user && user.role !== "REVIEWER" && <NextLink href="/workspace" aria-current={cur("/workspace")} className={navLink}>Workspace</NextLink>}
          {user?.role === "COMPANY_ADMIN" && <NextLink href="/org" aria-current={cur("/org")} className={navLink}>Organisation</NextLink>}
          {user && user.role !== "SUPER_ADMIN" && user.role !== "REVIEWER" && <NotificationsLink />}
          {/* Help is always last in the nav on every page (SC 3.2.6 Consistent Help). */}
          <NextLink href="/help" aria-current={cur("/help")} className={navLink}>Help</NextLink>
          {user === null && (
            <NextLink
              href="/login"
              aria-current={cur("/login")}
              className="ml-1 inline-flex min-h-11 items-center rounded-lg border-2 border-border px-4 font-semibold hover:bg-bg-inset aria-[current=page]:border-accent aria-[current=page]:text-accent"
            >
              Log in
            </NextLink>
          )}
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

const footLink = "inline-flex min-h-11 items-center rounded-lg px-1 underline-offset-4 hover:underline";

export function SiteFooter() {
  return (
    <footer className="mt-16 border-t-2 border-border-subtle bg-bg-subtle">
      <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-8 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex max-w-sm flex-col gap-2">
          <p className="inline-flex items-center gap-2.5 text-lg font-extrabold tracking-tight">
            <LogoMark className="size-7" />
            a11y
          </p>
          <p className="text-sm text-fg-muted">
            Accessibility audits you can act on. Automated findings are drafts until a person reviews and signs them off.
          </p>
        </div>
        <nav aria-label="Footer" className="flex flex-wrap items-center gap-x-5 sm:flex-1 sm:justify-end">
          <NextLink href="/accessibility" className={footLink}>Accessibility statement</NextLink>
          <NextLink href="/developers" className={footLink}>Developers</NextLink>
          <NextLink href="/help" className={footLink}>Help and contact</NextLink>
          <LegalLinks />
        </nav>
      </div>
      <div className="border-t-2 border-border-subtle">
        <p className="mx-auto flex max-w-6xl justify-end px-4 py-3 text-right text-sm text-fg-muted">
          <span>
            Powered by{" "}
            <a href="https://www.9th-direction.com" className="font-semibold text-accent underline underline-offset-4 hover:text-accent-hover">
              9th Direction Technology Solutions Private Limited
            </a>
          </span>
        </p>
      </div>
    </footer>
  );
}
