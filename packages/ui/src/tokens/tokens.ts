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
    "bg-subtle": "#f6f7fb",
    "bg-inset": "#e9edf5",
    fg: "#0b1220",
    "fg-muted": "#475467",
    border: "#667085", // component boundaries: >= 3:1 on bg (SC 1.4.11)
    "border-subtle": "#dde3ee", // decorative only
    accent: "#4338ca",
    "accent-fg": "#ffffff",
    "accent-hover": "#3730a3",
    "accent-subtle": "#eef0fd", // tinted surface for selected / highlighted items
    focus: "#4338ca",
    "focus-halo": "#ffffff", // second ring so focus shows on dark AND light surfaces
    danger: "#b3261e",
    "danger-bg": "#fdecea",
    "danger-fg": "#8c1d18",
    success: "#1b6e3a",
    "success-bg": "#e8f5ec",
    "success-fg": "#14532b",
    "warning-fg": "#7a4b00",
    "warning-bg": "#fff4e0",
    "inverse-bg": "#14123f", // dark brand band (hero, call to action)
    "inverse-fg": "#ffffff",
    "inverse-muted": "#c9cdf0",
    "inverse-accent": "#b6c0ff",
    "inverse-border": "#7f86c9",
  },
  dark: {
    bg: "#0b0f1a",
    "bg-subtle": "#121827",
    "bg-inset": "#1a2133",
    fg: "#eef1f8",
    "fg-muted": "#a9b3c7",
    border: "#8190a8",
    "border-subtle": "#2a3449",
    accent: "#a5b4fc",
    "accent-fg": "#0b0f1a",
    "accent-hover": "#c7d2fe",
    "accent-subtle": "#1c2142",
    focus: "#c7d2fe",
    "focus-halo": "#0b0f1a",
    danger: "#ff8a80",
    "danger-bg": "#3a1512",
    "danger-fg": "#ffb4ab",
    success: "#74d392",
    "success-bg": "#12301d",
    "success-fg": "#a6e8bb",
    "warning-fg": "#ffcc80",
    "warning-bg": "#3a2800",
    "inverse-bg": "#1a1850",
    "inverse-fg": "#ffffff",
    "inverse-muted": "#c9cdf0",
    "inverse-accent": "#b6c0ff",
    "inverse-border": "#8b92d4",
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
];
