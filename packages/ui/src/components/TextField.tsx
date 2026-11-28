"use client";

import {
  FieldError,
  Input,
  Label,
  Text,
  TextField as AriaTextField,
  type TextFieldProps as AriaTextFieldProps,
} from "react-aria-components";
import { cn } from "../cn";

export interface TextFieldProps extends Omit<AriaTextFieldProps, "className" | "isInvalid" | "validationBehavior"> {
  label: string;
  description?: string;
  /** Error message; its presence marks the field invalid and links it via aria-describedby. */
  error?: string;
  className?: string;
  placeholder?: string;
}

/**
 * Visible label (SC 3.3.2), inline error tied with aria-describedby (SC 3.3.1) and no
 * onPaste blocking (SC 3.3.8). Pass `autoComplete` for identity/password fields (SC 1.3.5).
 */
export function TextField({ label, description, error, className, placeholder, ...props }: TextFieldProps) {
  return (
    <AriaTextField {...props} isInvalid={!!error} validationBehavior="aria" className={cn("flex max-w-xl flex-col gap-1", className)}>
      <Label className="font-semibold">{label}</Label>
      {description && (
        <Text slot="description" className="text-sm text-fg-muted">
          {description}
        </Text>
      )}
      <Input
        placeholder={placeholder}
        className="min-h-11 rounded-lg border-2 border-border bg-bg px-3 py-2 text-fg shadow-sm transition-colors hover:border-fg-muted data-[invalid]:border-danger"
      />
      <FieldError className="flex items-start gap-1 text-sm font-medium text-danger">
        <span aria-hidden="true">⚠</span>
        <span>{error}</span>
      </FieldError>
    </AriaTextField>
  );
}
