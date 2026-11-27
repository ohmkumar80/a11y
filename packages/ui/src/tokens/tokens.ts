/**
 * Design tokens - the single source of truth for colour.
 * `pnpm build:tokens` generates src/tokens.css from this file, and
 * `pnpm check:contrast` (a blocking CI gate) fails if any pair below drops under its
 * WCAG 2.2 minimum in light OR dark mode (SC 1.4.3 text 4.5:1, SC 1.4.11 UI 3:1).
 */
export type Theme = "light" | "dark";

export const colors = {
  light: {
    bg: "#ffffff",
    "bg-subtle": "#f4f6f8",
    "bg-inset": "#e9edf1",
    fg: "#14181d",
    "fg-muted": "#4a5561",
    border: "#6b7785", // component boundaries: >= 3:1 on bg (SC 1.4.11)
    "border-subtle": "#cfd6de", // decorative only
    accent: "#0b4f9e",
    "accent-fg": "#ffffff",
    "accent-hover": "#083d7a",
    focus: "#0b4f9e",
    "focus-halo": "#ffffff", // second ring so focus shows on dark AND light surfaces
    danger: "#b3261e",
    "danger-bg": "#fdecea",
    "danger-fg": "#8c1d18",
    success: "#1b6e3a",
    "success-bg": "#e8f5ec",
    "success-fg": "#14532b",
    "warning-fg": "#7a4b00",
    "warning-bg": "#fff4e0",
  },
  dark: {
    bg: "#0f1318",
    "bg-subtle": "#171c23",
    "bg-inset": "#1f262f",
    fg: "#eef1f4",
    "fg-muted": "#aab4c0",
    border: "#8593a3",
    "border-subtle": "#364150",
    accent: "#7db4f5",
    "accent-fg": "#0f1318",
    "accent-hover": "#a3cbf8",
    focus: "#9fc7f8",
    "focus-halo": "#0f1318",
    danger: "#ff8a80",
    "danger-bg": "#3a1512",
    "danger-fg": "#ffb4ab",
    success: "#74d392",
    "success-bg": "#12301d",
    "success-fg": "#a6e8bb",
    "warning-fg": "#ffcc80",
    "warning-bg": "#3a2800",
  },
} as const;

export type ColorToken = keyof (typeof colors)["light"];

/** [foreground, background, minimum ratio, why] */
export const requiredPairs: ReadonlyArray<[ColorToken, ColorToken, number, string]> = [
  ["fg", "bg", 4.5, "body text"],
  ["fg", "bg-subtle", 4.5, "text on subtle panels"],
  ["fg", "bg-inset", 4.5, "text on inset panels"],
  ["fg-muted", "bg", 4.5, "secondary text"],
  ["fg-muted", "bg-subtle", 4.5, "secondary text on panels"],
  ["accent", "bg", 4.5, "links and accent text"],
  ["accent", "bg-subtle", 4.5, "links on panels"],
  ["accent-fg", "accent", 4.5, "primary button label"],
  ["accent-fg", "accent-hover", 4.5, "primary button label (hover)"],
  ["danger", "bg", 4.5, "error text"],
  ["danger-fg", "danger-bg", 4.5, "error banner text"],
  ["success-fg", "success-bg", 4.5, "success banner text"],
  ["warning-fg", "warning-bg", 4.5, "warning banner text"],
  ["border", "bg", 3, "input / control borders (SC 1.4.11)"],
  ["border", "bg-subtle", 3, "control borders on panels (SC 1.4.11)"],
  ["accent", "bg", 3, "meter / progress fill (SC 1.4.11)"],
  ["focus", "bg", 3, "focus ring vs page (SC 1.4.11, 2.4.13)"],
  ["focus", "bg-subtle", 3, "focus ring vs panel"],
  ["focus", "focus-halo", 3, "focus ring vs its halo"],
  ["danger", "danger-bg", 3, "error icon on banner"],
];
