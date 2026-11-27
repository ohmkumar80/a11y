import type { ReactNode } from "react";

/** Exactly one <h1> per page (SC 2.4.6, 1.3.1). */
export function Page({ title, intro, children, narrow }: { title: string; intro?: string; children?: ReactNode; narrow?: boolean }) {
  return (
    <div className={narrow ? "mx-auto flex max-w-md flex-col gap-6" : "flex flex-col gap-6"}>
      <div className="flex flex-col gap-2">
        <h1 className="text-3xl font-bold" tabIndex={-1}>{title}</h1>
        {intro && <p className="text-lg text-fg-muted">{intro}</p>}
      </div>
      {children}
    </div>
  );
}
