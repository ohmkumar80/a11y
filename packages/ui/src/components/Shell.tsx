import type { ReactNode } from "react";

/** First focusable element on every page (SC 2.4.1). Targets <main id="main" tabIndex={-1}>. */
export function SkipLink({ href = "#main", children = "Skip to main content" }: { href?: string; children?: ReactNode }) {
  return (
    <a
      href={href}
      className="a11y-sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-[60] focus:rounded-md focus:border-2 focus:border-accent focus:bg-bg focus:px-4 focus:py-3 focus:font-semibold focus:text-accent"
    >
      {children}
    </a>
  );
}
