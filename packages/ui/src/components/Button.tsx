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
  primary: "border-fg bg-accent text-accent-fg shadow-glow hover:bg-accent-hover",
  secondary: "border-fg bg-bg text-fg shadow-glow hover:bg-bg-inset",
  danger: "border-fg bg-danger text-bg shadow-glow hover:opacity-90",
} as const;

/** Targets are 44x44 minimum on primary actions (SC 2.5.8 requires 24x24). */
export function Button({ variant = "primary", className, pendingLabel = "Loading", children, ...props }: ButtonProps) {
  return (
    <AriaButton
      {...props}
      className={cn(
        "inline-flex min-h-11 min-w-11 items-center [overflow-wrap:normal] justify-center gap-2 rounded-xl border-2 px-4 py-2 font-bold transition-[background-color,box-shadow,transform] duration-100 hover:-translate-x-px hover:-translate-y-px hover:shadow-lift active:translate-x-0.5 active:translate-y-0.5 active:shadow-none",
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
