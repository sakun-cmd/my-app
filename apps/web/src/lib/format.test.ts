import { describe, expect, it } from "vitest";

import { formatPercent } from "./format";

describe("formatPercent", () => {
  it("formats ratios as Japanese percentages", () => {
    expect(formatPercent(0.253)).toBe("25.3%");
  });
});

