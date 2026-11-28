"use client";

import type { ReactNode } from "react";
import {
  Dialog as AriaDialog,
  DialogTrigger,
  Heading,
  Modal,
  ModalOverlay,
} from "react-aria-components";
import { Button } from "./Button";

export { DialogTrigger };

export interface DialogProps {
  title: string;
  children: ReactNode | ((close: () => void) => ReactNode);
  isOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
}

/**
 * Modal dialog: focus is trapped, Esc closes, focus returns to the trigger, and the rest
 * of the page is inert (all handled by React Aria). Use inside <DialogTrigger>.
 */
export function Dialog({ title, children, ...props }: DialogProps) {
  return (
    <ModalOverlay {...props} isDismissable className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4">
      <Modal className="max-h-full w-full max-w-lg overflow-auto rounded-2xl border-2 border-border-subtle bg-bg p-6 shadow-2xl">
        <AriaDialog className="flex flex-col gap-4 outline-none">
          {({ close }) => (
            <>
              <Heading slot="title" className="text-xl font-bold">{title}</Heading>
              {typeof children === "function" ? children(close) : children}
              <div className="flex justify-end">
                <Button variant="secondary" onPress={close}>Close</Button>
              </div>
            </>
          )}
        </AriaDialog>
      </Modal>
    </ModalOverlay>
  );
}
