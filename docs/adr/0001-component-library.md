# ADR 0001: React Aria Components is the only UI primitive layer

- **Status:** Accepted (PROJECT_PLAN open decision 1)
- **Date:** 2026-11-26

## Context
The product must meet WCAG 2.2 AA itself. Mixing primitive libraries (Radix + React Aria) gives two different
focus, keyboard and announcement models, and bugs that only appear at the seams.

## Decision
`@a11y/ui` wraps **React Aria Components** and nothing else for interactive primitives. Apps import from `@a11y/ui`,
never from `react-aria-components` directly (the one exception is re-exports there). Styling is Tailwind v4 with
colour tokens in `packages/ui/src/tokens/tokens.ts`; contrast is checked in CI for light and dark.

## Consequences
- Dialog focus trapping, Select/Tabs/Table keyboard behaviour and live announcements come from a tested library.
- RAC's Table renders `role="grid"`; use it for data tables with a labelled region for horizontal scroll.
- Toast is still `UNSTABLE_*` in RAC 1.22; we wrap it in `Toast.tsx` so a rename is a one-file change.
