"use client";

import {
  FieldError,
  Label,
  Text,
  TextArea as AriaTextArea,
  TextField as AriaTextField,
  type TextFieldProps as AriaTextFieldProps,
} from "react-aria-components";
import { cn } from "../cn";

export interface TextAreaProps extends Omit<AriaTextFieldProps, "className" | "isInvalid" | "validationBehavior"> {
  label: string;
  description?: string;
  error?: string;
  className?: string;
  rows?: number;
  /** Keep the label for assistive technology but do not show it (e.g. inside a table row whose header already names it). */
  labelHidden?: boolean;
}

/** Multi-line field with the same guarantees as TextField: label, linked description and error, paste allowed. */
export function TextArea({ label, description, error, className, rows = 3, labelHidden, ...props }: TextAreaProps) {
  return (
    <AriaTextField {...props} isInvalid={!!error} validationBehavior="aria" className={cn("flex max-w-xl flex-col gap-1", className)}>
      <Label className={cn("font-semibold", labelHidden && "a11y-sr-only")}>{label}</Label>
      {description && <Text slot="description" className="text-sm text-fg-muted">{description}</Text>}
      <AriaTextArea rows={rows} className="min-h-11 rounded-lg border-2 border-border bg-bg px-3 py-2 text-fg shadow-sm transition-colors hover:border-fg-muted data-[invalid]:border-danger" />
      <FieldError className="flex items-start gap-1 text-sm font-medium text-danger">
        <span aria-hidden="true">⚠</span>
        <span>{error}</span>
      </FieldError>
    </AriaTextField>
  );
}
