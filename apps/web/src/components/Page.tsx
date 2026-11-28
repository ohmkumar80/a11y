import type { ReactNode } from "react";

/** Exactly one <h1> per page (SC 2.4.6, 1.3.1). `narrow` is the centred card used by sign-in style forms. */
export function Page({ title, intro, children, narrow }: { title: string; intro?: string; children?: ReactNode; narrow?: boolean }) {
  const heading = (
    <div className="flex flex-col gap-2">
      <h1 className={narrow ? "text-2xl font-extrabold sm:text-3xl" : "text-3xl font-extrabold sm:text-4xl"} tabIndex={-1}>{title}</h1>
      {intro && <p className={narrow ? "text-fg-muted" : "max-w-3xl text-lg text-fg-muted"}>{intro}</p>}
    </div>
  );
  if (narrow) {
    return (
      <div className="mx-auto flex w-full max-w-md flex-col gap-6 rounded-2xl border-2 border-border-subtle bg-bg p-6 shadow-sm sm:p-8">
        {heading}
        {children}
      </div>
    );
  }
  return (
    <div className="a11y-page-body flex flex-col gap-8">
      {heading}
      {children}
    </div>
  );
}
