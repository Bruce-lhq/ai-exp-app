import type { Field } from "../../app/api";
export function parseValue(text: string, field: Field): unknown {
  if (text === "" && field.nullable) return null;
  if (field.kind === "string") return text;
  if (field.choices?.some((value) => String(value) === text))
    return field.choices.find((value) => String(value) === text);
  if (field.kind === "boolean") return text === "true";
  const match = text
    .trim()
    .match(/^([+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?)\s*([kmbt])?$/i);
  if (!match) throw new Error("请输入有效数值，可使用 K、M、B");
  const value =
    Number(match[1]) *
    ({ k: 1e3, m: 1e6, b: 1e9, t: 1e12 }[match[2]?.toLowerCase() as "k"] || 1);
  if (
    !Number.isFinite(value) ||
    (field.kind === "integer" && !Number.isSafeInteger(value))
  )
    throw new Error("请输入有效整数");
  if (field.constraints?.min !== undefined && value < field.constraints.min)
    throw new Error(`不能小于 ${field.constraints.min}`);
  if (field.constraints?.max !== undefined && value > field.constraints.max)
    throw new Error(`不能大于 ${field.constraints.max}`);
  return value;
}
export const same = (a: unknown, b: unknown) =>
  JSON.stringify(a) === JSON.stringify(b);
export function move<T>(list: T[], from: number, to: number): T[] {
  const next = [...list];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}

// Presentation only: never round the numeric parameter stored in the editor.
export function displayNumber(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return value == null ? "" : String(value);
  if (value !== 0 && Math.abs(value) < 0.01) return value.toExponential().replace(/e\+?(-?)0*(\d+)/, "e$1$2");
  for (const [suffix, factor] of [["T", 1e12], ["B", 1e9], ["M", 1e6], ["K", 1e3]] as const) {
    if (Math.abs(value) >= factor) return `${value / factor}${suffix}`;
  }
  return String(value);
}
