"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

/** The home page lays out its own full-width bands; every other page sits in the standard centred container. */
export function MainContainer({ children }: { children: ReactNode }) {
  const home = usePathname() === "/";
  return (
    // tabIndex=-1 so the skip link and route changes can move focus here.
    <main id="main" tabIndex={-1} className={home ? "w-full flex-1 outline-none" : "mx-auto w-full max-w-6xl flex-1 px-4 py-10 outline-none"}>
      {children}
    </main>
  );
}
