/** Decorative mark: the name beside it carries the meaning, so it is hidden from assistive tech.
 *  A solid square with a check, drawn "in focus" with an offset ring: the mark of an accessibility product. */
export function LogoMark({ className = "size-9", onInk = false }: { className?: string; onInk?: boolean }) {
  return (
    <svg viewBox="0 0 36 36" aria-hidden="true" focusable="false" className={className}>
      <rect x="1.25" y="1.25" width="33.5" height="33.5" rx="3" fill="none" strokeWidth="2.5" className={onInk ? "stroke-inverse-accent" : "stroke-accent"} />
      <rect x="7" y="7" width="22" height="22" rx="1.5" className={onInk ? "fill-inverse-fg" : "fill-fg"} />
      <path d="M12 18.4l4.3 4.3 7.9-8.4" fill="none" strokeWidth="3" strokeLinecap="square" className={onInk ? "stroke-inverse-bg" : "stroke-bg"} />
    </svg>
  );
}
