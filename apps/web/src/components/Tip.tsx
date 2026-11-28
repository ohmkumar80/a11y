"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

const KEY = "a11y-tips";
const Ctx = createContext<{ on: boolean; set: (on: boolean) => void }>({ on: true, set: () => {} });

/** Whether to show the guidance notes. On by default; the choice is kept in this browser only. */
export function TipsProvider({ children }: { children: ReactNode }) {
  const [on, setOn] = useState(true);
  useEffect(() => { if (localStorage.getItem(KEY) === "off") setOn(false); }, []);
  const set = useCallback((v: boolean) => { setOn(v); localStorage.setItem(KEY, v ? "on" : "off"); }, []);
  const value = useMemo(() => ({ on, set }), [on, set]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
export const useTips = () => useContext(Ctx);

/** A short note that sits beside the work and says what to do or why. It is plain text in the page (no hover-only
 *  tooltips, SC 1.4.13) and can be switched off for everyone with the "Tips" control in the navigation. */
export function Tip({ title = "Tip", children, className = "" }: { title?: string; children: ReactNode; className?: string }) {
  const { on } = useTips();
  if (!on) return null;
  return (
    <div role="note" className={`a11y-note ${className}`}>
      <p className="a11y-kicker !text-fg">{title}</p>
      <div className="mt-0.5 text-fg">{children}</div>
    </div>
  );
}
