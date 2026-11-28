/**
 * Design tokens - the single source of truth for colour.
 * `pnpm build:tokens` generates src/tokens.css from this file, and
 * `pnpm check:contrast` (a blocking CI gate) fails if any pair below drops under its
 * WCAG 2.2 minimum in light OR dark mode (SC 1.4.3 text 4.5:1, SC 1.4.11 UI 3:1).
 */
export type Theme = "light" | "dark";

export const colors = {
  light: {
    bg: "#fbf9f3", // paper
    "bg-subtle": "#f3efe4",
    "bg-inset": "#e8e2d1",
    fg: "#16130e", // ink
    "fg-muted": "#58524a",
    border: "#6c6558", // component boundaries: >= 3:1 on bg (SC 1.4.11)
    "border-subtle": "#d8d0bd", // decorative rules only
    accent: "#b93c0c", // signal: actions, current page, marks
    "accent-fg": "#fffaf2",
    "accent-hover": "#962f09",
    "accent-subtle": "#fbe8da", // tinted surface for selected / highlighted items
    "accent-2": "#0f6a58", // "checked" green: passes, verified, done
    focus: "#16130e",
    "focus-halo": "#fbf9f3", // second ring so focus shows on dark AND light surfaces
    danger: "#b3261e",
    "danger-bg": "#fbe7e3",
    "danger-fg": "#8c1d18",
    success: "#1b6e3a",
    "success-bg": "#e4f2e8",
    "success-fg": "#14532b",
    "warning-fg": "#7a4b00",
    "warning-bg": "#fff1d6",
    "inverse-bg": "#16130e", // ink surfaces (side navigation, footer, call to action)
    "inverse-fg": "#fbf9f3",
    "inverse-muted": "#cdc6b5",
    "inverse-accent": "#ff9d6b",
    "inverse-accent-2": "#7fe3c4",
    "inverse-border": "#8f8776",
  },
  dark: {
    bg: "#13110d",
    "bg-subtle": "#1c1914",
    "bg-inset": "#27231c",
    fg: "#f4efe3",
    "fg-muted": "#b9b1a0",
    border: "#948b7a",
    "border-subtle": "#3a352b",
    accent: "#ff9d6b",
    "accent-fg": "#16130e",
    "accent-hover": "#ffb48c",
    "accent-subtle": "#3a2418",
    "accent-2": "#7fe3c4",
    focus: "#ffb48c",
    "focus-halo": "#13110d",
    danger: "#ff8a80",
    "danger-bg": "#3a1512",
    "danger-fg": "#ffb4ab",
    success: "#74d392",
    "success-bg": "#12301d",
    "success-fg": "#a6e8bb",
    "warning-fg": "#ffcc80",
    "warning-bg": "#3a2800",
    "inverse-bg": "#0b0907",
    "inverse-fg": "#f4efe3",
    "inverse-muted": "#cdc6b5",
    "inverse-accent": "#ff9d6b",
    "inverse-accent-2": "#7fe3c4",
    "inverse-border": "#948b7a",
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
  ["accent", "accent-subtle", 4.5, "links and selected labels on tinted surfaces"],
  ["fg", "accent-subtle", 4.5, "text on tinted surfaces"],
  ["fg-muted", "bg-inset", 4.5, "secondary text on inset panels"],
  ["border", "bg-inset", 3, "control borders on inset panels (SC 1.4.11)"],
  ["inverse-fg", "inverse-bg", 4.5, "text on the brand band"],
  ["inverse-muted", "inverse-bg", 4.5, "secondary text on the brand band"],
  ["inverse-accent", "inverse-bg", 4.5, "eyebrow text and links on the brand band"],
  ["inverse-border", "inverse-bg", 3, "outlines on the brand band (SC 1.4.11)"],
  ["inverse-bg", "inverse-fg", 4.5, "label of a white button on the brand band"],
  ["accent-2", "bg", 4.5, "secondary brand colour as text or icon on the page"],
  ["accent-2", "bg-subtle", 4.5, "secondary brand colour on panels"],
  ["inverse-accent-2", "inverse-bg", 4.5, "secondary brand colour on the brand band"],
];
