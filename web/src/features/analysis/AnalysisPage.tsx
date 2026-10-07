import { useEffect, useState } from "react";
import { Download, GripVertical, SlidersHorizontal } from "lucide-react";
import { api, items } from "../../app/api";
import { Empty } from "../../app/ui";
import {
  ExperimentChart,
  downloadPng,
  seriesColors,
  type ChartSettings,
  type Series,
} from "./ExperimentChart";
import { useSharedPlotView } from "./useSharedPlotView";
import { TablePanel } from "./TablePanel";
const initial: ChartSettings = {
  metric: "val_ppl",
  xAxis: "tokens",
  title: "验证集困惑度",
  xLabel: "Trained tokens (B)",
  yLabel: "val_ppl",
  xScale: "linear",
  yScale: "logarithmic",
  width: 1536,
  height: 1044,
  pixelRatio: 1.5,
  xMin: 0,
  xMax: 10.75,
};
function initialSettings(): ChartSettings {
  const raw = localStorage.getItem("analysis.settings") || "{}";
  let saved: Partial<ChartSettings> = {};
  try { saved = JSON.parse(raw); } catch { saved = {}; }
  if (localStorage.getItem("analysis.settings.v2") !== "1") {
    localStorage.setItem("analysis.settings.v2", "1");
    saved.yScale = "logarithmic";
  }
  if (localStorage.getItem("analysis.settings.v3") !== "1") {
    localStorage.setItem("analysis.settings.v3", "1");
    saved.xLabel = initial.xLabel;
    saved.width = initial.width;
    saved.height = initial.height;
    saved.pixelRatio = initial.pixelRatio;
    saved.xMin = initial.xMin;
    saved.xMax = initial.xMax;
  }
  if (localStorage.getItem("analysis.settings.v4") !== "1") {
    localStorage.setItem("analysis.settings.v4", "1");
    saved.height = Math.round((saved.width || initial.width) * 1401 / 2061);
  }
  return { ...initial, ...saved };
}
function initialAppearance(): Record<string, { name?: string; color?: string; order?: number }> {
  try { return JSON.parse(localStorage.getItem("analysis.appearance") || "{}"); } catch { return {}; }
}
function initialIds(): string[] {
  try {
    const value = JSON.parse(localStorage.getItem("analysis.ids") || "[]");
    return Array.isArray(value) ? value.filter((id): id is string => typeof id === "string") : [];
  } catch {
    return [];
  }
}
let lastPlot: { key: string; series: Series[]; warnings: string[]; metrics: string[] } | undefined;
const plotKey = (ids: string[], settings: ChartSettings) => JSON.stringify([ids, settings.metric, settings.xAxis]);
export function AnalysisPage({ notify }: { notify: (s: string) => void }) {
  const [view, setView] = useState<"plot" | "table">("plot");
  const [plotLoading, setPlotLoading] = useState(false);
  const [history, setHistory] = useState<any[]>([]),
    [ids, setIds] = useState<string[]>(initialIds),
    [settings, setSettings] = useState<ChartSettings>(initialSettings),
    [series, setSeries] = useState<Series[]>(() => lastPlot?.key === plotKey(ids, settings) ? lastPlot.series : []),
    [warnings, setWarnings] = useState<string[]>(() => lastPlot?.key === plotKey(ids, settings) ? lastPlot.warnings : []),
    [metrics, setMetrics] = useState(() => lastPlot?.key === plotKey(ids, settings) ? lastPlot.metrics : ["val_ppl"]),
    [advanced, setAdvanced] = useState(false),
    [appearance, setAppearance] = useState(initialAppearance),
    [appearanceDrag, setAppearanceDrag] = useState("");
  useSharedPlotView(settings, appearance, setSettings, setAppearance, notify);
  useEffect(() => {
    localStorage.setItem("analysis.appearance", JSON.stringify(appearance));
  }, [appearance]);
  useEffect(() => {
    const refresh = () => api("/api/history")
      .then((x) => {
        const visible = items(x).filter((h) => h.visibility !== "archived");
        setHistory(visible);
        const available = new Set(visible.map((h) => h.id));
        setIds((current) => current.filter((id) => available.has(id)));
      })
      .catch((e) => notify(e.message));
    refresh();
    window.addEventListener("workspace-sync-changed", refresh);
    return () => window.removeEventListener("workspace-sync-changed", refresh);
  }, []);
  useEffect(() => {
    localStorage.setItem("analysis.ids", JSON.stringify(ids));
    localStorage.setItem("analysis.settings", JSON.stringify(settings));
  }, [JSON.stringify(ids), JSON.stringify(settings)]);
  useEffect(() => {
    let alive = true;
    setPlotLoading(true);
    api("/api/analysis/series", {
      history_ids: ids,
      metric: settings.metric,
      x_axis: settings.xAxis,
    })
      .then((x) => {
        if (alive) {
          const available: string[] = x.metrics || [];
          const axes: string[] = x.axes || [];
          const metric = available.length && !available.includes(settings.metric) ? available[0] : settings.metric;
          const axis = axes.length && !axes.includes(settings.xAxis) ? (axes.includes("step") ? "step" : axes[0]) : settings.xAxis;
          if (metric !== settings.metric || axis !== settings.xAxis) {
            setSettings((current) => ({ ...current, metric, xAxis: axis,
              ...(metric !== current.metric ? { yLabel: metric, yScale: metric.toLowerCase().includes("ppl") ? "logarithmic" : "linear",
                title: current.title === initial.title ? metric : current.title } : {}),
              ...(axis !== current.xAxis ? { xLabel: axis === "tokens" ? "Trained tokens (B)" : axis === "step" ? "训练 step" : "有效训练耗时 (s)",
                xMin: undefined, xMax: undefined } : {}),
            }));
          }
          const snapshot = {key: plotKey(ids, settings), series: x.series || [],
            warnings: (x.warnings || []).map((w: any) => w.message || w),
            metrics: [...new Set<string>([settings.metric, ...(x.metrics || []).filter((m: string) => !/^ca\/L\d+\/T\d+\//.test(m))])]};
          lastPlot = snapshot;
          setSeries(snapshot.series);
          setWarnings(snapshot.warnings);
          setMetrics(snapshot.metrics);
        }
      })
      .catch((e) => {
        if (alive) {
          setWarnings([e.message]);
        }
      }).finally(() => { if (alive) setPlotLoading(false); });
    return () => {
      alive = false;
    };
  }, [JSON.stringify(ids), settings.metric, settings.xAxis, JSON.stringify(history.map((h) => [h.id, h.content_revision]))]);
  const change = (p: Partial<ChartSettings>) =>
    setSettings((s) => ({ ...s, ...p }));
  const nonpositive = series.some((s) =>
    s.points.some(
      (p) =>
        (settings.xScale === "logarithmic" && p.x <= 0) ||
        (settings.yScale === "logarithmic" && p.y <= 0),
    ),
  );
  const orderedSeries = [...series].sort((a, b) =>
    (appearance[a.id]?.order ?? series.indexOf(a)) - (appearance[b.id]?.order ?? series.indexOf(b)),
  );
  return (
    <>
      <div className="page-heading analysis-heading">
        <div>
          <span className="eyebrow">COMPARE & EXPORT</span>
          <h1>画图与列表</h1>
          <p>选择实验，比较结果。满意后下载 PNG 或导出 Markdown。</p>
        </div>
        <div className="analysis-view-switch" role="tablist" aria-label="画图与列表视图">
          <button id="plot-tab" role="tab" aria-selected={view === "plot"} aria-controls="plot-panel" onClick={() => setView("plot")}>画图</button>
          <button id="table-tab" role="tab" aria-selected={view === "table"} aria-controls="table-panel" onClick={() => setView("table")}>列表</button>
        </div>
        <details className="history-picker">
          <summary>
            选择历史实验 <span className="count">{ids.length}</span>
          </summary>
          <div>
            {!history.length ? (
              <p className="muted">先到历史管理导入实验。</p>
            ) : (
              <>
                <button className="subtle" onClick={() => setIds(history.every((h) => ids.includes(h.id)) ? [] : history.map((h) => h.id))}>{history.every((h) => ids.includes(h.id)) ? "取消全选" : "全选"}</button>
                {history.map((h) => (
                  <label className="check" key={h.id}>
                    <input type="checkbox" checked={ids.includes(h.id)} onChange={(e) => setIds(e.target.checked ? [...ids, h.id] : ids.filter((id) => id !== h.id))} />
                    {h.name || h.display_name}
                    {history.filter((other) => (other.name || other.display_name) === (h.name || h.display_name)).length > 1 &&
                      <small className="muted"> · {h.status === "running" || h.status === "external_running" ? "运行中" : h.status === "stopped" ? "已停止" : h.status} · {h.id.slice(0, 8)}</small>}
                  </label>
                ))}
              </>
            )}
          </div>
        </details>
      </div>
      <section className="panel" id="plot-panel" role="tabpanel" aria-labelledby="plot-tab" hidden={view !== "plot"}>
        <div className="panel-heading plot-toolbar">
          <h3>曲线对比</h3>
          <label>
            指标
            <select
              aria-label="指标"
              value={settings.metric}
              onChange={(e) =>
                change({ metric: e.target.value, yLabel: e.target.value,
                  yScale: e.target.value.toLowerCase().includes('ppl') ? 'logarithmic' : 'linear' })
              }
            >
              {metrics.map((m) => (
                <option key={m}>{m}</option>
              ))}
            </select>
          </label>
          <label>
            横轴
            <select
              aria-label="横轴"
              value={settings.xAxis}
              onChange={(e) =>
                change({
                  xAxis: e.target.value,
                  xLabel: {
                    tokens: "Trained tokens (B)",
                    step: "训练 step",
                    elapsed_s: "有效训练耗时 (s)",
                  }[e.target.value],
                  ...(e.target.value === "tokens"
                    ? { xMin: 0, xMax: 10.75 }
                    : { xMin: undefined, xMax: undefined }),
                })
              }
            >
              <option value="tokens">训练 tokens</option>
              <option value="step">step</option>
              <option value="elapsed_s">实际训练耗时</option>
            </select>
          </label>
          <label>
            图标题
            <input
              value={settings.title}
              onChange={(e) => change({ title: e.target.value })}
            />
          </label>
          <button onClick={() => setAdvanced(!advanced)}>
            <SlidersHorizontal size={15} />
            图表设置
          </button>
          <button
            className="primary"
            disabled={!series.some((s) => s.points.length)}
            onClick={() => downloadPng(orderedSeries, settings, appearance)}
          >
            <Download size={15} />
            下载 PNG
          </button>
        </div>
        {advanced && (
          <div className="chart-controls">
            {(["x", "y"] as const).map((axis) => (
              <div key={axis}>
                <label>
                  {axis.toUpperCase()} 轴标题
                  <input
                    value={settings[`${axis}Label`]}
                    onChange={(e) =>
                      change({ [`${axis}Label`]: e.target.value })
                    }
                  />
                </label>
                <label>
                  刻度
                  <select
                    value={settings[`${axis}Scale`]}
                    onChange={(e) =>
                      change({ [`${axis}Scale`]: e.target.value })
                    }
                  >
                    <option value="linear">线性</option>
                    <option value="logarithmic">对数</option>
                  </select>
                </label>
                {(["Min", "Max"] as const).map((bound) => (
                  <label key={bound}>
                    {bound === "Min" ? "下限" : "上限"}
                    <input
                      type="number"
                      placeholder="自动"
                      value={settings[`${axis}${bound}`] ?? ""}
                      onChange={(e) =>
                        change({
                          [`${axis}${bound}`]:
                            e.target.value === ""
                              ? undefined
                              : Number(e.target.value),
                        })
                      }
                    />
                  </label>
                ))}
              </div>
            ))}
            <div>
              {(["width", "height", "pixelRatio"] as const).map((key) => (
                <label key={key}>
                  {
                    {
                      width: "导出宽度",
                      height: "导出高度",
                      pixelRatio: "清晰度倍率",
                    }[key]
                  }
                  <input
                    type="number"
                    min="1"
                    max={key === "pixelRatio" ? 4 : 6000}
                    value={settings[key]}
                    onChange={(e) => {
                      const n = Number(e.target.value);
                      if (n > 0 && n <= (key === "pixelRatio" ? 4 : 6000))
                        change({ [key]: n });
                    }}
                  />
                </label>
              ))}
            </div>
            {orderedSeries.map((s, i) => (
              <div key={s.id} draggable onDragStart={() => setAppearanceDrag(s.id)} onDragOver={(e) => e.preventDefault()} onDrop={() => {
                const from = orderedSeries.findIndex((x) => x.id === appearanceDrag);
                if (from < 0 || from === i) return;
                const next = [...orderedSeries];
                const [item] = next.splice(from, 1);
                next.splice(i, 0, item);
                setAppearance((current) => Object.fromEntries(next.map((x, index) => [x.id, { ...current[x.id], order: index }])));
              }}>
                <GripVertical size={14} />
                <input
                  aria-label={`${s.name} 颜色`}
                  type="color"
                  value={seriesColors(orderedSeries, appearance)[i]}
                  onChange={(e) => {
                    const duplicate = Object.entries(appearance).some(([id, value]) => id !== s.id && value.color?.toLowerCase() === e.target.value.toLowerCase());
                    if (duplicate) { notify("每条曲线需要使用不同颜色"); return; }
                    setAppearance((a) => ({ ...a, [s.id]: { ...a[s.id], color: e.target.value } }));
                  }}
                />
                <label>
                  图例
                  <input
                    value={appearance[s.id]?.name ?? s.name}
                    onChange={(e) =>
                      setAppearance((a) => ({
                        ...a,
                        [s.id]: { ...a[s.id], name: e.target.value.trim() },
                      }))
                    }
                  />
                </label>
              </div>
            ))}
          </div>
        )}
        {warnings.map((w, i) => (
          <p className="warning" key={i}>
            {w}
          </p>
        ))}
        {nonpositive && (
          <p className="warning">
            对数坐标无法显示非正数点；已跳过这些点，实验选择保持不变。
          </p>
        )}
        {series.some((s) => s.points.length) ? (
          <ExperimentChart
            series={orderedSeries}
            settings={settings}
            appearance={appearance}
          />
        ) : plotLoading && ids.length > 0 ? (
          <p role="status" className="empty"><span className="spinner" /> 正在读取本地缓存…</p>
        ) : (
          <Empty>
            <div className="empty-plot">
              <i />
              <i />
              <i />
            </div>
            <h3>
              {ids.length ? "所选指标暂无可绘制数据" : "选择实验，开始对比"}
            </h3>
            <p>缺少指标的实验会暂时跳过，切换指标后仍保留勾选。</p>
          </Empty>
        )}
      </section>
      <div id="table-panel" role="tabpanel" aria-labelledby="table-tab" hidden={view !== "table"}>
        <TablePanel ids={ids} history={history} notify={notify} metrics={metrics} />
      </div>
    </>
  );
}
