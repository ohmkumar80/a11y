"use client";

import { Link as AriaLink, type LinkProps as AriaLinkProps } from "react-aria-components";
import { cn } from "../cn";

/** Links are always underlined: colour must not be the only cue (SC 1.4.1). */
export function Link({ className, ...props }: Omit<AriaLinkProps, "className"> & { className?: string }) {
  return (
    <AriaLink
      {...props}
      className={cn("inline-block min-h-6 text-accent underline underline-offset-2 hover:text-accent-hover", className)}
    />
  );
}
