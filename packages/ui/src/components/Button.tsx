"use client";

import { Button as AriaButton, type ButtonProps as AriaButtonProps } from "react-aria-components";
import { cn } from "../cn";

export interface ButtonProps extends Omit<AriaButtonProps, "className"> {
  variant?: "primary" | "secondary" | "danger";
  className?: string;
  /** Visually hidden text announced while pending, e.g. "Saving". */
  pendingLabel?: string;
}

const variants = {
  primary: "bg-accent text-accent-fg hover:bg-accent-hover border-transparent",
  secondary: "bg-bg text-fg border-border hover:bg-bg-inset",
  danger: "bg-danger text-bg border-transparent hover:opacity-90",
} as const;

/** Targets are 44x44 minimum on primary actions (SC 2.5.8 requires 24x24). */
export function Button({ variant = "primary", className, pendingLabel = "Loading", children, ...props }: ButtonProps) {
  return (
    <AriaButton
      {...props}
      className={cn(
        "inline-flex min-h-11 min-w-11 items-center justify-center gap-2 rounded-md border-2 px-4 py-2 font-semibold",
        "aria-disabled:opacity-60 data-[disabled]:opacity-60 data-[pending]:cursor-progress",
        variants[variant],
        className,
      )}
    >
      {(renderProps) => (
        <>
          {typeof children === "function" ? children(renderProps) : children}
          {renderProps.isPending && <span className="a11y-sr-only">{pendingLabel}</span>}
        </>
      )}
    </AriaButton>
  );
}
