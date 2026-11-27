import { describe, expect, it } from "vitest";
import { contrastRatio } from "./contrast";
import { colors, requiredPairs } from "./tokens";

describe("contrast maths", () => {
  it("matches WCAG reference values", () => {
    expect(contrastRatio("#000000", "#ffffff")).toBeCloseTo(21, 1);
    expect(contrastRatio("#777777", "#ffffff")).toBeCloseTo(4.48, 2);
    expect(contrastRatio("#767676", "#ffffff")).toBeGreaterThanOrEqual(4.5);
  });
});

describe.each(["light", "dark"] as const)("design tokens (%s)", (theme) => {
  it.each(requiredPairs)("%s on %s >= %s:1 (%s)", (fg, bg, min) => {
    expect(contrastRatio(colors[theme][fg], colors[theme][bg])).toBeGreaterThanOrEqual(min);
  });
});
