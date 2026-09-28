import { expect, test } from "vitest";
import { parseValue, move } from "../src/features/parameters/values";
import { partitionSeries } from "../src/features/analysis/series";
const field = { key: "tokens", kind: "integer", default: 0, has_default: true };
test("human units normalize with case and reject invalid experiment values", () => {
  expect(parseValue("1.25B", field)).toBe(1250000000);
  expect(parseValue("2m", field)).toBe(2000000);
  expect(() => parseValue("abc", field)).toThrow();
  expect(() => parseValue("1.5", field)).toThrow();
  expect(() => parseValue("Infinity", field)).toThrow();
});
test("mixed numeric or symbolic choices preserve semantic types", () => {
  const f = { ...field, kind: "number_or_choice", choices: ["auto", "none"] };
  expect(parseValue("auto", f)).toBe("auto");
  expect(parseValue("2K", f)).toBe(2000);
});
test("drag order changes copy without mutating submitted order", () => {
  const original = ["a", "b", "c"];
  expect(move(original, 2, 0)).toEqual(["c", "a", "b"]);
  expect(original).toEqual(["a", "b", "c"]);
});
test("missing metric never removes selected experiment", () => {
  const selected = ["a", "b"];
  expect(partitionSeries(selected, { a: [1], b: [] })).toEqual({
    visible: ["a"],
    missing: ["b"],
  });
  expect(selected).toEqual(["a", "b"]);
  expect(partitionSeries(selected, { a: [1], b: [2] }).visible).toEqual([
    "a",
    "b",
  ]);
});
