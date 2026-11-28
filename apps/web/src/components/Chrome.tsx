"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { AppShell, isAppPath } from "./AppShell";
import { SiteFooter, SiteHeader } from "./SiteHeader";

/** Public pages get the masthead and footer; the signed-in app gets the side-navigation shell. */
export function Chrome({ children }: { children: ReactNode }) {
  const path = usePathname();
  if (isAppPath(path)) return <AppShell>{children}</AppShell>;
  const home = path === "/";
  return (
    <div className="flex min-h-screen flex-col">
      <SiteHeader />
      {/* tabIndex=-1 so the skip link and route changes can move focus here. */}
      <main id="main" tabIndex={-1} className={home ? "w-full flex-1 outline-none" : "mx-auto w-full max-w-7xl flex-1 px-4 pb-20 pt-10 outline-none sm:px-8"}>
        {children}
      </main>
      <SiteFooter />
    </div>
  );
}
