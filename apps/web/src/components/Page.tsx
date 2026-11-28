import type { ReactNode } from "react";
import { LogoMark } from "./Logo";

const points = [
  ["01", "Several scan engines, one merged result"],
  ["02", "Plain-language guidance and checked fixes"],
  ["03", "Reports a named person signs off"],
];

/** Exactly one <h1> per page (SC 2.4.6, 1.3.1). `narrow` is the split sign-in layout used by account forms. */
export function Page({ title, intro, children, narrow }: { title: string; intro?: string; children?: ReactNode; narrow?: boolean }) {
  if (narrow) {
    return (
      <div className="a11y-boxed mx-auto grid w-full max-w-5xl shadow-lift lg:grid-cols-[0.85fr_1.15fr]">
        {/* Decorative: repeats what the home page says, so it is only shown where there is room. */}
        <div className="a11y-ink hidden flex-col justify-between gap-12 p-10 lg:flex">
          <p className="inline-flex items-center gap-3 font-sans text-2xl font-bold tracking-tight">
            <LogoMark onInk />
            a11y
          </p>
          <div className="flex flex-col gap-8">
            <p className="font-display text-4xl font-semibold leading-[1.1]">
              Accessibility audits you can <span className="a11y-infocus">act on</span>
            </p>
            <ul className="flex flex-col gap-4">
              {points.map(([n, t]) => (
                <li key={n} className="flex items-baseline gap-4 border-t border-inverse-border/60 pt-3 text-inverse-muted">
                  <span className="a11y-kicker shrink-0">{n}</span>
                  {t}
                </li>
              ))}
            </ul>
          </div>
          <p className="a11y-kicker">Built to WCAG 2.2 AA</p>
        </div>
        <div className="flex flex-col justify-center gap-6 p-6 sm:p-10">
          <div className="flex flex-col gap-2">
            <h1 className="text-4xl font-semibold" tabIndex={-1}>{title}</h1>
            {intro && <p className="text-fg-muted">{intro}</p>}
          </div>
          {children}
        </div>
      </div>
    );
  }
  return (
    <div className="a11y-page-body flex flex-col gap-10">
      <div className="flex flex-col gap-3 border-b-2 border-fg pb-6">
        <h1 className="text-4xl font-semibold sm:text-5xl" tabIndex={-1}>{title}</h1>
        {intro && <p className="max-w-3xl text-lg text-fg-muted">{intro}</p>}
      </div>
      {children}
    </div>
  );
}
