import type { ElementType, ReactNode } from "react";
import { cn } from "../cn";

export interface CardProps {
  /** Element to render, e.g. "li" inside a list or "section" with its own heading. Default "div". */
  as?: ElementType;
  className?: string;
  children: ReactNode;
  /** Slightly stronger surface for emphasised content. */
  tone?: "default" | "subtle" | "accent";
}

const tones = {
  default: "border-fg bg-bg",
  subtle: "border-border-subtle bg-bg-subtle",
  accent: "border-accent bg-accent-subtle",
} as const;

/** Presentational surface only: no role, no tabindex. Put headings and landmarks inside it. */
export function Card({ as: Tag = "div", tone = "default", className, children }: CardProps) {
  return <Tag className={cn("rounded-lg border-[1.5px] p-5", tones[tone], className)}>{children}</Tag>;
}
