"use client";

import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

/**
 * Next.js client-side navigation neither moves focus nor announces the new page. On every
 * route change we (1) announce the new document title in a polite live region and (2) move
 * focus to the page's <h1> (or <main>), so keyboard and screen-reader users start at the top.
 * The first load is skipped: the browser already handled it.
 */
export function RouteAnnouncer() {
  const pathname = usePathname();
  const first = useRef(true);
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    // Wait a tick so the new page's <title> and <h1> are in the DOM.
    const id = setTimeout(() => {
      setMessage(`${document.title} page loaded`);
      const target = document.querySelector<HTMLElement>("main h1") ?? document.getElementById("main");
      if (target) {
        if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
        target.focus({ preventScroll: false });
      }
    }, 100);
    return () => clearTimeout(id);
  }, [pathname]);

  return (
    <div aria-live="polite" aria-atomic="true" className="a11y-sr-only" data-testid="route-announcer">
      {message}
    </div>
  );
}
