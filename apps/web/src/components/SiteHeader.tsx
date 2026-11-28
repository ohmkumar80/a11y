"use client";

import NextLink from "next/link";
import { usePathname } from "next/navigation";
import { Button } from "@a11y/ui";
import { LegalLinks } from "./LegalLinks";
import { LogoMark } from "./Logo";
import { useAuth } from "./AuthProvider";

export { LogoMark } from "./Logo";

const navLink =
  "inline-flex min-h-11 items-center px-3 font-semibold underline-offset-[6px] decoration-2 hover:underline aria-[current=page]:underline aria-[current=page]:decoration-accent aria-[current=page]:decoration-4";

/** Header for public pages (home, sign-in, help, legal). Signed-in work happens in the side-navigation shell. */
export function SiteHeader() {
  const { user, logout } = useAuth();
  const path = usePathname();
  const cur = (href: string) => (path === href || path.startsWith(`${href}/`) ? ("page" as const) : undefined);

  // Not sticky: nothing may obscure focused content (SC 2.4.11).
  return (
    <header className="border-b-2 border-fg bg-bg">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 py-2 sm:px-8">
        <NextLink href="/" className="inline-flex min-h-11 items-center gap-3 pr-2 font-sans text-2xl font-bold tracking-tight">
          <LogoMark />
          a11y
        </NextLink>
        <nav aria-label="Main" className="flex flex-wrap items-center gap-x-1 gap-y-1">
          {user && <NextLink href="/workspace" aria-current={cur("/workspace")} className={navLink}>Workspace</NextLink>}
          <NextLink href="/developers" aria-current={cur("/developers")} className={navLink}>Developers</NextLink>
          {/* Help is always last in the nav on every page (SC 3.2.6 Consistent Help). */}
          <NextLink href="/help" aria-current={cur("/help")} className={navLink}>Help</NextLink>
          {user === null && (
            <>
              <NextLink href="/login" aria-current={cur("/login")} className={navLink}>Log in</NextLink>
              <NextLink
                href="/signup"
                aria-current={cur("/signup")}
                className="ml-2 inline-flex min-h-11 items-center border-2 border-fg bg-accent px-4 font-bold text-accent-fg shadow-glow transition-[transform,box-shadow] hover:-translate-x-px hover:-translate-y-px hover:bg-accent-hover hover:shadow-lift"
              >
                Start free trial
              </NextLink>
            </>
          )}
          {user && (
            <Button variant="secondary" className="ml-2" onPress={() => void logout().then(() => (location.href = "/login"))}>
              Log out
            </Button>
          )}
        </nav>
      </div>
    </header>
  );
}

const footLink = "inline-flex min-h-11 items-center text-inverse-muted underline-offset-4 hover:text-inverse-fg hover:underline";

export function FooterLinks({ className = "", linkClassName = footLink }: { className?: string; linkClassName?: string }) {
  return (
    <nav aria-label="Footer" className={className}>
      <NextLink href="/accessibility" className={linkClassName}>Accessibility statement</NextLink>
      <NextLink href="/developers" className={linkClassName}>Developers</NextLink>
      <NextLink href="/help" className={linkClassName}>Help and contact</NextLink>
      <LegalLinks linkClassName={linkClassName} />
    </nav>
  );
}

export function PoweredBy({ className = "", paper = false }: { className?: string; paper?: boolean }) {
  return (
    <p className={`flex justify-end text-right text-sm ${paper ? "text-fg-muted" : "text-inverse-muted"} ${className}`}>
      <span>
        Powered by{" "}
        <a href="https://www.9th-direction.com" className={`font-bold underline underline-offset-4 ${paper ? "text-fg hover:text-accent" : "text-inverse-fg hover:text-inverse-accent"}`}>
          9th Direction Technology Solutions Private Limited
        </a>
      </span>
    </p>
  );
}

export function SiteFooter() {
  return (
    <footer className="a11y-ink">
      <div className="mx-auto grid max-w-7xl gap-10 px-4 py-14 sm:px-8 md:grid-cols-[1.4fr_1fr]">
        <div className="flex max-w-md flex-col gap-4">
          <p className="inline-flex items-center gap-3 font-sans text-3xl font-bold tracking-tight">
            <LogoMark onInk />
            a11y
          </p>
          <p className="text-inverse-muted">
            Accessibility audits you can act on. Automated findings are drafts until a person reviews and signs them off.
          </p>
        </div>
        <FooterLinks className="flex flex-col sm:grid sm:grid-cols-2 sm:content-start sm:gap-x-8" />
      </div>
      <div className="border-t border-inverse-border/50">
        <PoweredBy className="mx-auto max-w-7xl px-4 py-4 sm:px-8" />
      </div>
    </footer>
  );
}
