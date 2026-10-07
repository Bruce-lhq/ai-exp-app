import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { api } from "../../app/api";
import type { ChartSettings } from "./ExperimentChart";
type Appearance = Record<string, { name?: string; color?: string; order?: number }>;
type View = { settings: ChartSettings; appearance: Appearance };
export function useSharedPlotView(settings: ChartSettings, appearance: Appearance,
  setSettings: Dispatch<SetStateAction<ChartSettings>>, setAppearance: Dispatch<SetStateAction<Appearance>>,
  notify: (message: string) => void) {
  const current = useRef<View>({ settings, appearance });
  current.current = { settings, appearance };
  const baseline = useRef(localStorage.getItem("analysis.shared-baseline") || JSON.stringify(current.current));
  const remember = (value: string) => { baseline.current = value; localStorage.setItem("analysis.shared-baseline", value); };
  const saving = useRef(false);
  const mounted = useRef(false);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    mounted.current = true;
    async function load(first = false) {
      if (saving.current) return;
      if (!first && JSON.stringify(current.current) !== baseline.current) {
        const snapshot = current.current;
        saving.current = true;
        try {
          await api("/api/workspace-sync/view", snapshot, "PUT", { background: true });
          remember(JSON.stringify(snapshot));
        } finally { saving.current = false; }
        return;
      }
      const before = JSON.stringify(current.current);
      const saved = await api<Partial<View>>("/api/workspace-sync/view", undefined, undefined, { background: true });
      if (!mounted.current) return;
      if (saved.settings && saved.appearance && before === JSON.stringify(current.current) && before === baseline.current) {
        const next = { settings: saved.settings, appearance: saved.appearance };
        remember(JSON.stringify(next));
        setSettings(next.settings); setAppearance(next.appearance);
      } else if (first && !saved.settings) {
        saving.current = true;
        try {
          const snapshot = current.current;
          await api("/api/workspace-sync/view", snapshot, "PUT", { background: true });
          remember(JSON.stringify(snapshot));
        } finally { saving.current = false; }
      }
      if (first && mounted.current) setReady(true);
    }
    load(true).catch(() => { if (mounted.current) setReady(true); });
    const refresh = () => load().catch(() => {});
    const timer = setInterval(refresh, 10000);
    window.addEventListener("workspace-sync-changed", refresh);
    return () => { mounted.current = false; clearInterval(timer); window.removeEventListener("workspace-sync-changed", refresh); };
  }, []);
  const signature = JSON.stringify({ settings, appearance });
  useEffect(() => {
    if (!ready || signature === baseline.current) return;
    let active = true;
    const timer = setTimeout(async () => {
      while (saving.current && active) await new Promise(resolve => setTimeout(resolve, 100));
      if (!active) return;
      saving.current = true;
      try {
        await api("/api/workspace-sync/view", { settings, appearance }, "PUT", { background: true });
        remember(signature);
      } catch (error) {
        if (active) notify(`图表设置尚未保存到后台，本机设置已保留：${(error as Error).message}`);
      } finally { saving.current = false; }
    }, 500);
    return () => { active = false; clearTimeout(timer); };
  }, [ready, signature]);
}
