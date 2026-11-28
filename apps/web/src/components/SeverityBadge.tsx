import { SEVERITY_ICON, SEVERITY_LABEL, type Severity } from "@/lib/scans";

const tone: Record<Severity, string> = {
  critical: "border-danger bg-danger-bg text-danger-fg",
  serious: "border-warning-fg bg-warning-bg text-warning-fg",
  moderate: "border-border bg-bg-inset text-fg",
  minor: "border-border-subtle bg-bg-subtle text-fg-muted",
};

/** Severity is conveyed by the word and a shape as well as colour (SC 1.4.1). */
export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap border-[1.5px] px-2 py-0.5 text-sm font-bold ${tone[severity]}`}>
      <span aria-hidden="true">{SEVERITY_ICON[severity]}</span>
      {SEVERITY_LABEL[severity]}
    </span>
  );
}

const statTone: Record<Severity, string> = {
  critical: "border-danger bg-danger-bg text-danger-fg",
  serious: "border-warning-fg bg-warning-bg text-warning-fg",
  moderate: "border-border bg-bg-inset text-fg",
  minor: "border-border-subtle bg-bg-subtle text-fg",
};
export const severityStat = (s: Severity) => statTone[s];
