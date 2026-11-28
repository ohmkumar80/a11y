"use client";

import { Button, Text, UNSTABLE_Toast as Toast, UNSTABLE_ToastContent as ToastContent, UNSTABLE_ToastRegion as ToastRegion } from "react-aria-components";
import { ToastQueue } from "react-stately";
import { cn } from "../cn";

export interface ToastValue {
  title: string;
  description?: string;
  kind?: "info" | "success" | "error";
}

export const toasts = new ToastQueue<ToastValue>({ maxVisibleToasts: 3 });

/** Info/success auto-dismiss after a generous 8s. Errors persist until dismissed (SC 2.2.1). */
export function notify(value: ToastValue) {
  return toasts.add(value, { timeout: value.kind === "error" ? undefined : 8000 });
}

const kindStyles = {
  info: "border-border bg-bg",
  success: "border-success bg-success-bg text-success-fg",
  error: "border-danger bg-danger-bg text-danger-fg",
} as const;
const icons = { info: "ℹ", success: "✓", error: "⚠" } as const;

/**
 * Render once near the end of <body>. Toasts live in a polite live region, are never the only
 * place important info appears, sit at the bottom so they don't cover the focused field, and are
 * reachable with F6.
 */
export function ToastProvider() {
  return (
    <ToastRegion queue={toasts} aria-label="Notifications" className="fixed bottom-4 right-4 z-40 flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2">
      {({ toast }) => (
        <Toast toast={toast} className={cn("flex items-start gap-3 rounded-lg border-2 p-3.5 shadow-lift", kindStyles[toast.content.kind ?? "info"])}>
          <span aria-hidden="true" className="mt-0.5">{icons[toast.content.kind ?? "info"]}</span>
          <ToastContent className="flex flex-1 flex-col">
            <Text slot="title" className="font-semibold">{toast.content.title}</Text>
            {toast.content.description && <Text slot="description">{toast.content.description}</Text>}
          </ToastContent>
          <Button slot="close" aria-label="Dismiss notification" className="grid min-h-11 min-w-11 place-items-center rounded-md border-2 border-transparent hover:bg-bg-inset">
            <span aria-hidden="true">✕</span>
          </Button>
        </Toast>
      )}
    </ToastRegion>
  );
}
