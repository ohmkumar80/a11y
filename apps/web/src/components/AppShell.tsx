"use client";

import NextLink from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Suspense, useState, type ReactNode } from "react";
import { Button } from "@a11y/ui";
import { ADMIN_TABS } from "@/lib/adminTabs";
import { useFlags } from "@/lib/flags";
import { useAuth } from "./AuthProvider";
import { Icon, type IconName } from "./Icon";
import { LogoMark } from "./Logo";
import { NotificationsLink } from "./NotificationsLink";
import { FooterLinks, PoweredBy } from "./SiteHeader";
import { useTips } from "./Tip";

/** Pages that belong to the signed-in app and get the side navigation. Everything else is a public page. */
export const APP_PATHS = ["/workspace", "/admin", "/org", "/review", "/notifications"];
export const isAppPath = (path: string) => APP_PATHS.some((p) => path === p || path.startsWith(`${p}/`));

const item =
  "flex min-h-11 items-center gap-3 border-l-4 border-transparent px-4 py-2 text-inverse-muted transition-colors hover:bg-white/10 hover:text-inverse-fg aria-[current=page]:border-inverse-accent aria-[current=page]:bg-white/10 aria-[current=page]:font-bold aria-[current=page]:text-inverse-fg";

function Group({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div role="group" aria-label={label} className="flex flex-col">
      <p aria-hidden="true" className="a11y-kicker px-4 pb-1 pt-5">{label}</p>
      {children}
    </div>
  );
}

function Link({ href, icon, children, current }: { href: string; icon: IconName; children: ReactNode; current: boolean }) {
  return (
    <NextLink href={href} aria-current={current ? "page" : undefined} className={item}>
      <Icon name={icon} />
      {children}
    </NextLink>
  );
}

function NavLinks() {
  const { user } = useAuth();
  const flags = useFlags();
  const path = usePathname();
  const tab = useSearchParams().get("tab") ?? "overview";
  const role = user?.role;
  const on = (p: string) => path === p || path.startsWith(`${p}/`);

  return (
    <>
      {role === "SUPER_ADMIN" && (
        <>
          {(["Platform", "Product", "System"] as const).map((g) => (
            <Group key={g} label={g}>
              {ADMIN_TABS.filter((t) => t.group === g).map((t) => (
                <Link key={t.id} href={`/admin?tab=${t.id}`} icon="dot" current={on("/admin") && tab === t.id}>{t.label}</Link>
              ))}
            </Group>
          ))}
        </>
      )}
      {(role === "REVIEWER" || role === "SUPER_ADMIN") && (
        <Group label="Reviews">
          <Link href="/review" icon="queue" current={on("/review")}>Review queue</Link>
        </Group>
      )}
      {(role === "COMPANY_ADMIN" || role === "STANDARD_USER") && (
        <Group label="Work">
          <Link href="/workspace" icon="dashboard" current={path === "/workspace" || (on("/workspace") && !on("/workspace/documents"))}>Workspace</Link>
          {flags.documents && <Link href="/workspace/documents" icon="documents" current={on("/workspace/documents")}>Documents</Link>}
          <NotificationsLink className={item} icon={<Icon name="bell" />} />
        </Group>
      )}
      {role === "COMPANY_ADMIN" && (
        <Group label="Organisation">
          <Link href="/org" icon="org" current={on("/org")}>Organisation</Link>
        </Group>
      )}
      {/* Help is always last in the nav on every page (SC 3.2.6 Consistent Help). */}
      <Group label="Support">
        <Link href="/help" icon="help" current={on("/help")}>Help</Link>
      </Group>
    </>
  );
}

const sideButton =
  "flex min-h-11 w-full items-center gap-2 border-2 border-inverse-border px-3 py-2 font-bold text-inverse-fg transition-colors hover:bg-white/10 aria-pressed:border-inverse-accent";

function TipsSwitch() {
  const { on, set } = useTips();
  return (
    <button type="button" aria-pressed={on} onClick={() => set(!on)} className={sideButton}>
      <Icon name="tip" />
      Tips: {on ? "on" : "off"}
    </button>
  );
}

/** Signed-in layout: a fluid content area beside a side navigation. Below the large breakpoint the navigation folds into
 *  a Menu button at the top, so it never crowds a narrow or zoomed screen (SC 1.4.10). Nothing here is sticky over content. */
export function AppShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[17.5rem_minmax(0,1fr)]">
      <header className="a11y-ink flex flex-col lg:sticky lg:top-0 lg:h-screen lg:overflow-y-auto">
        <div className="flex items-center justify-between gap-3 px-4 py-3 lg:px-5 lg:py-5">
          <NextLink href="/workspace" className="inline-flex min-h-11 items-center gap-3 font-sans text-2xl font-bold tracking-tight">
            <LogoMark onInk />
            a11y
          </NextLink>
          <Button variant="secondary" className="lg:hidden" aria-expanded={open} aria-controls="app-nav" onPress={() => setOpen(!open)}>
            <Icon name={open ? "close" : "menu"} />
            Menu
          </Button>
        </div>
        <div id="app-nav" className={`${open ? "flex" : "hidden"} flex-1 flex-col lg:flex`}>
          <nav aria-label="Main" className="flex-1 pb-4">
            <Suspense fallback={null}><NavLinks /></Suspense>
          </nav>
          <div className="flex flex-col gap-3 border-t border-inverse-border/50 p-4">
            {user && (
              <p className="text-sm text-inverse-muted">
                <span className="block font-bold text-inverse-fg [overflow-wrap:anywhere]">{user.email}</span>
                {user.organization_name}
              </p>
            )}
            <TipsSwitch />
            {user && (
              <button type="button" className={sideButton} onClick={() => void logout().then(() => (location.href = "/login"))}>
                Log out
              </button>
            )}
          </div>
        </div>
      </header>

      <div className="flex min-w-0 flex-col">
        {/* tabIndex=-1 so the skip link and route changes can move focus here. */}
        <main id="main" tabIndex={-1} className="w-full flex-1 px-4 pb-16 pt-8 outline-none sm:px-8 xl:px-12">
          {children}
        </main>
        <footer className="border-t-2 border-fg bg-bg-subtle">
          <div className="flex flex-col gap-2 px-4 py-4 sm:px-8 sm:flex-row sm:items-center sm:justify-between xl:px-12">
            <FooterLinks className="flex flex-wrap gap-x-4" linkClassName="inline-flex min-h-11 items-center text-fg-muted underline-offset-4 hover:text-fg hover:underline" />
            <PoweredBy paper />
          </div>
        </footer>
      </div>
    </div>
  );
}
