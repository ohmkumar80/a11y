const paths = {
  dashboard: "M4 4h7v9H4zM13 4h7v5h-7zM13 11h7v9h-7zM4 15h7v5H4z",
  documents: "M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6",
  bell: "M6 9a6 6 0 0112 0c0 6 2 7 2 7H4s2-1 2-7M10 20a2 2 0 004 0",
  org: "M4 21V5l8-2v18M12 9h8v12M7 9h2M7 13h2M7 17h2M15 13h2M15 17h2",
  queue: "M4 13l2-8h12l2 8v6H4zM4 13h5l1 2h4l1-2h5",
  help: "M9.5 9a2.5 2.5 0 115 0c0 2-2.5 2-2.5 4M12 17h.01M12 3a9 9 0 100 18 9 9 0 000-18",
  dot: "M12 8l4 4-4 4-4-4z",
  menu: "M4 7h16M4 12h16M4 17h16",
  close: "M6 6l12 12M18 6L6 18",
  tip: "M9 18h6M10 21h4M12 3a6 6 0 00-3.5 10.9c.9.7 1.5 1.6 1.5 2.6h4c0-1 .6-1.9 1.5-2.6A6 6 0 0012 3z",
  arrow: "M5 12h14M13 6l6 6-6 6",
} as const;
export type IconName = keyof typeof paths;

/** Decorative: every use sits beside a text label, so the icon is hidden from assistive tech. */
export function Icon({ name, className = "size-5" }: { name: IconName; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" className={`${className} shrink-0`} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="square" strokeLinejoin="miter">
      <path d={paths[name]} />
    </svg>
  );
}
