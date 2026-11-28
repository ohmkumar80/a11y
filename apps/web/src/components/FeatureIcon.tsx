const paths = {
  layers: "M12 3l9 5-9 5-9-5 9-5zM3 12.5l9 5 9-5M3 17l9 5 9-5",
  book: "M12 6.5C10.5 5 8 4.5 4 4.5v13c4 0 6.5.5 8 2 1.5-1.5 4-2 8-2v-13c-4 0-6.5.5-8 2zM12 6.5v13",
  shield: "M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6l7-3zM9 12l2 2 4-4",
  monitor: "M3 5h18v11H3zM8 20h8M12 16v4",
  file: "M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6",
  code: "M8 8l-4 4 4 4M16 8l4 4-4 4M13.5 6l-3 12",
} as const;

export type IconName = keyof typeof paths;

/** Decorative: every use sits next to a text heading, so the icon is hidden from assistive tech. */
export function FeatureIcon({ name }: { name: IconName }) {
  return (
    <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-accent-subtle text-accent">
      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" className="size-6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d={paths[name]} />
      </svg>
    </span>
  );
}
