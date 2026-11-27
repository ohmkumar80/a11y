import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, expect } from "vitest";
import * as axeMatchers from "vitest-axe/matchers";

expect.extend(axeMatchers);
afterEach(cleanup);

// jsdom lacks these; React Aria's overlays and our meters touch them.
globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} };
