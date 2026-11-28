"use client";

import {
  Button,
  FieldError,
  Label,
  ListBox,
  ListBoxItem,
  Popover,
  Select as AriaSelect,
  SelectValue,
  type Key,
} from "react-aria-components";
import { cn } from "../cn";

export interface SelectOption {
  id: Key;
  label: string;
}

export interface SelectProps {
  label: string;
  options: SelectOption[];
  value?: Key | null;
  defaultValue?: Key;
  onChange?: (key: Key | null) => void;
  error?: string;
  name?: string;
  isRequired?: boolean;
  className?: string;
  /** Keep the label for assistive technology but do not show it (e.g. inside a table row). */
  labelHidden?: boolean;
}

export function Select({ label, options, error, className, labelHidden, ...props }: SelectProps) {
  return (
    <AriaSelect
      {...props}
      selectedKey={props.value}
      defaultSelectedKey={props.defaultValue}
      onSelectionChange={props.onChange}
      isInvalid={!!error}
      validationBehavior="aria"
      className={cn("flex max-w-xl flex-col gap-1", className)}
    >
      <Label className={cn("font-bold", labelHidden && "a11y-sr-only")}>{label}</Label>
      <Button className="flex min-h-11 items-center justify-between gap-2 rounded-md border-2 border-fg bg-bg px-3 py-2 text-left hover:bg-bg-subtle data-[invalid]:border-danger data-[invalid]:bg-danger-bg">
        <SelectValue />
        <span aria-hidden="true">▾</span>
      </Button>
      <FieldError className="text-sm font-medium text-danger">{error}</FieldError>
      <Popover className="min-w-(--trigger-width) rounded-md border-2 border-fg bg-bg shadow-lift">
        <ListBox className="max-h-72 overflow-auto p-1 outline-none">
          {options.map((o) => (
            <ListBoxItem
              key={o.id}
              id={o.id}
              textValue={o.label}
              className="flex min-h-11 cursor-default items-center gap-2 rounded-lg px-3 py-2 data-[focused]:bg-accent-subtle data-[selected]:font-bold"
            >
              {({ isSelected }) => (
                <>
                  <span aria-hidden="true" className="w-4">{isSelected ? "✓" : ""}</span>
                  {o.label}
                </>
              )}
            </ListBoxItem>
          ))}
        </ListBox>
      </Popover>
    </AriaSelect>
  );
}
