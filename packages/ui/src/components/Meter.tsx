"use client";

import { Label, Meter as AriaMeter, ProgressBar as AriaProgressBar } from "react-aria-components";

export interface MeterProps {
  label: string;
  value: number;
  maxValue: number;
  /** Spoken value, e.g. "7 of 10 seats used". Required: percentages alone are unhelpful. */
  valueText: string;
  /** Switches to a warning style at/above this fraction. State is also shown as text + icon. */
  warnAt?: number;
}

/** role="meter" with aria-valuetext. Warning state uses text and an icon, not colour alone. */
export function Meter({ label, value, maxValue, valueText, warnAt = 0.9 }: MeterProps) {
  const warn = value / maxValue >= warnAt;
  return (
    <AriaMeter value={value} minValue={0} maxValue={maxValue} valueLabel={valueText} aria-valuetext={valueText} className="flex flex-col gap-1">
      {({ percentage }) => (
        <>
          <div className="flex justify-between gap-2">
            <Label className="font-semibold">{label}</Label>
            <span>{warn && <span aria-hidden="true">⚠ </span>}{valueText}{warn && " (nearly full)"}</span>
          </div>
          <div className="a11y-meter-track h-3 overflow-hidden rounded-full border border-border bg-bg-inset">
            <div className="a11y-meter-fill h-full bg-accent" style={{ width: `${percentage}%` }} />
          </div>
        </>
      )}
    </AriaMeter>
  );
}

export interface ProgressBarProps {
  label: string;
  /** Omit for an indeterminate bar. */
  value?: number;
  valueText?: string;
}

export function ProgressBar({ label, value, valueText }: ProgressBarProps) {
  return (
    <AriaProgressBar value={value} isIndeterminate={value === undefined} valueLabel={valueText} className="flex flex-col gap-1">
      {({ percentage, valueText: vt, isIndeterminate }) => (
        <>
          <div className="flex justify-between gap-2">
            <Label className="font-semibold">{label}</Label>
            <span>{isIndeterminate ? "In progress" : vt}</span>
          </div>
          <div className="a11y-progress-track h-3 overflow-hidden rounded-full border border-border bg-bg-inset">
            <div className="a11y-progress-fill h-full bg-accent" style={{ width: isIndeterminate ? "40%" : `${percentage}%` }} />
          </div>
        </>
      )}
    </AriaProgressBar>
  );
}
