import { describe, expect, it } from "vitest";
import { displayNumber, parseValue } from "../src/features/parameters/values";
describe("numeric display", () => {
  it("uses automatic units and normalized scientific notation without rounding parameters", () => {
    expect(displayNumber(1234567)).toBe("1.234567M");
    expect(displayNumber(.0002)).toBe("2e-4");
    expect(displayNumber(-.000002)).toBe("-2e-6");
    expect(displayNumber(.01)).toBe("0.01");
    expect(displayNumber("  note  ")).toBe("  note  ");
    for (const value of [0, 2000, 1234567, 1e12, .0002]) {
      expect(parseValue(displayNumber(value), { kind: "number" } as any)).toBe(value);
    }
  });
});
