"use client";

import { useEffect, useRef } from "react";
import { cn } from "../cn";

export interface FormError {
  /** id of the input this error belongs to, so the summary link can focus it */
  fieldId?: string;
  message: string;
}

/**
 * Error summary shown after a failed submit. It takes focus on mount (SC 3.3.1 / G139), lists each
 * error as a link to its field, and is a role="alert" region for AT that doesn't move focus.
 */
export function ErrorSummary({ errors, title = "There is a problem" }: { errors: FormError[]; title?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (errors.length) ref.current?.focus();
  }, [errors]);
  if (!errors.length) return null;
  return (
    <div ref={ref} tabIndex={-1} role="alert" className="rounded-md border-2 border-danger bg-danger-bg p-4 text-danger-fg">
      <h2 className="text-lg font-bold">{title}</h2>
      <ul className="mt-2 list-disc pl-5">
        {errors.map((e, i) => (
          <li key={i}>
            {e.fieldId ? (
              <a
                href={`#${e.fieldId}`}
                className="underline"
                onClick={(ev) => {
                  ev.preventDefault();
                  document.getElementById(e.fieldId!)?.focus();
                }}
              >
                {e.message}
              </a>
            ) : (
              e.message
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function VisuallyHidden({ children, className }: { children: React.ReactNode; className?: string }) {
  return <span className={cn("a11y-sr-only", className)}>{children}</span>;
}

/** Banner for non-field messages (e.g. "check your email"). Polite, not a focus thief. */
export function StatusMessage({ children, kind = "info" }: { children: React.ReactNode; kind?: "info" | "success" }) {
  return (
    <div role="status" className={cn("rounded-md border-2 p-3", kind === "success" ? "border-success bg-success-bg text-success-fg" : "border-border bg-bg-subtle")}>
      {children}
    </div>
  );
}
