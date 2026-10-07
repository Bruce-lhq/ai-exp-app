import { useEffect, useState } from "react";
export type ThemeMode = "system" | "light" | "dark";
export function savedTheme(): ThemeMode {
  try {
    const mode = localStorage.getItem("appearance.theme");
    if (mode === "light" || mode === "dark") return mode;
  } catch {}
  return "system";
}
export function useTheme() {
  const [mode, setMode] = useState<ThemeMode>(savedTheme);
  useEffect(() => {
    const system = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => {
      const dark = mode === "dark" || (mode === "system" && system.matches);
      document.documentElement.dataset.theme = dark ? "dark" : "light";
      document.querySelector('meta[name="theme-color"]')?.setAttribute("content", dark ? "#101622" : "#f2f5f9");
      window.dispatchEvent(new Event("ai-exp-theme"));
    };
    try { localStorage.setItem("appearance.theme", mode); } catch {}
    update();
    system.addEventListener("change", update);
    return () => system.removeEventListener("change", update);
  }, [mode]);
  return [mode, setMode] as const;
}
export function useDarkTheme() {
  const [dark, setDark] = useState(() => document.documentElement.dataset.theme === "dark");
  useEffect(() => {
    const update = () => setDark(document.documentElement.dataset.theme === "dark");
    update();
    window.addEventListener("ai-exp-theme", update);
    return () => window.removeEventListener("ai-exp-theme", update);
  }, []);
  return dark;
}
