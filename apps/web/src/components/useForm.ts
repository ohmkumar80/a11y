"use client";

import { useState } from "react";
import type { FormError } from "@a11y/ui";
import type { Problem } from "@/lib/api";

/**
 * Shared submit handling: one `submitting` flag, a map of field errors for inline messages and a
 * list for the error summary (SC 3.3.1). Field ids are `field-<name>` so the summary can focus them.
 */
export function useForm() {
  const [submitting, setSubmitting] = useState(false);
  const [problem, setProblem] = useState<Problem | null>(null);

  const errors: FormError[] = problem ? [{ fieldId: problem.field ? `field-${problem.field}` : undefined, message: problem.detail }] : [];
  const fieldError = (name: string) => (problem?.field === name ? problem.detail : undefined);

  async function submit(fn: () => Promise<Problem | null>) {
    setSubmitting(true);
    setProblem(null);
    const p = await fn();
    setProblem(p);
    setSubmitting(false);
    return p === null;
  }
  return { submitting, errors, fieldError, submit, problem };
}
