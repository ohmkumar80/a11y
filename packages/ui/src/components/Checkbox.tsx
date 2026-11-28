"use client";

import { Checkbox as AriaCheckbox, type CheckboxProps as AriaCheckboxProps } from "react-aria-components";
import { cn } from "../cn";

export interface CheckboxProps extends Omit<AriaCheckboxProps, "className" | "children"> {
  label: string;
  className?: string;
}

/** Native checkbox semantics (React Aria). The visible box carries the focus ring because the
 *  real input is visually hidden; state is shown by a check mark, not colour alone. */
export function Checkbox({ label, className, ...props }: CheckboxProps) {
  return (
    <AriaCheckbox {...props} className={cn("group flex min-h-11 items-center gap-3", className)}>
      {({ isSelected }) => (
        <>
          <span
            aria-hidden="true"
            className="flex size-6 shrink-0 items-center justify-center rounded-md border-2 border-border bg-bg font-bold group-data-[selected]:bg-accent group-data-[selected]:text-accent-fg group-data-[focus-visible]:outline-[3px] group-data-[focus-visible]:outline-offset-2 group-data-[focus-visible]:outline-(--a11y-focus)"
          >
            {isSelected ? "✓" : ""}
          </span>
          <span>{label}</span>
        </>
      )}
    </AriaCheckbox>
  );
}
