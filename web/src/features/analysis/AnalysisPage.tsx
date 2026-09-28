import { useEffect, useState } from "react";
import { Download, GripVertical, SlidersHorizontal } from "lucide-react";
import { api, items } from "../../app/api";
import { Empty } from "../../app/ui";
import {
  ExperimentChart,
  downloadPng,
  palette,
  type ChartSettings,
  type Series,
} from "./ExperimentChart";
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
  height: 1032,
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
  return { ...initial, ...saved };
}
function initialAppearance(): Record<string, { name?: string; color?: string; order?: number }> {
  try { return JSON.parse(localStorage.getItem("analysis.appearance") || "{}"); } catch { return {}; }
}
export function AnalysisPage({ notify }: { notify: (s: string) => void }) {
  const [history, setHistory] = useState<any[]>([]),
    [ids, setIds] = useState<string[]>(() =>
      JSON.parse(localStorage.getItem("analysis.ids") || "[]"),
    ),
    [settings, setSettings] = useState<ChartSettings>(initialSettings),
    [series, setSeries] = useState<Series[]>([]),
    [warnings, setWarnings] = useState<string[]>([]),
    [metrics, setMetrics] = useState(["val_ppl"]),
    [advanced, setAdvanced] = useState(false),
    [appearance, setAppearance] = useState(initialAppearance),
    [appearanceDrag, setAppearanceDrag] = useState("");
  useEffect(() => {
    localStorage.setItem("analysis.appearance", JSON.stringify(appearance));
  }, [appearance]);
  useEffect(() => {
    api("/api/history")
      .then((x) => setHistory(items(x).filter((h) => h.visibility !== "archived")))
      .catch((e) => notify(e.message));
  }, []);
  useEffect(() => {
    localStorage.setItem("analysis.ids", JSON.stringify(ids));
    localStorage.setItem("analysis.settings", JSON.stringify(settings));
    let alive = true;
    api("/api/analysis/series", {
      history_ids: ids,
      metric: settings.metric,
      x_axis: settings.xAxis,
    })
      .then((x) => {
        if (alive) {
          setSeries(x.series || []);
          setWarnings((x.warnings || []).map((w: any) => w.message || w));
        }
      })
      .catch((e) => {
        if (alive) {
          setSeries([]);
          setWarnings([e.message]);
        }
      });
    return () => {
      alive = false;
    };
  }, [JSON.stringify(ids), JSON.stringify(settings)]);
  useEffect(() => {
    Promise.all(
      ids.map((id) =>
        api(`/api/history/${id}/metrics`).catch(() => ({ metadata: {} })),
      ),
    ).then((all) =>
      setMetrics([
        ...new Set([
          "val_ppl",
          ...all.flatMap((d) => Object.keys(d.metadata || {})),
        ]),
      ]),
    );
  }, [JSON.stringify(ids)]);
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
      <div className="page-heading">
        <div>
          <span className="eyebrow">COMPARE & EXPORT</span>
          <h1>画图与列表</h1>
          <p>选择实验，比较结果。满意后下载 PNG 或导出 Markdown。</p>
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
                <button className="subtle" onClick={() => setIds(ids.length === history.length ? [] : history.map((h) => h.id))}>{ids.length === history.length ? "取消全选" : "全选"}</button>
                {history.map((h) => (
                  <label className="check" key={h.id}>
                    <input type="checkbox" checked={ids.includes(h.id)} onChange={(e) => setIds(e.target.checked ? [...ids, h.id] : ids.filter((id) => id !== h.id))} />
                    {h.name || h.display_name}
                  </label>
                ))}
              </>
            )}
          </div>
        </details>
      </div>
      <section className="panel">
        <div className="panel-heading">
          <h3>曲线对比</h3>
          <button
            className="primary"
            disabled={!series.some((s) => s.points.length)}
            onClick={() => downloadPng(series, settings, appearance)}
          >
            <Download size={15} />
            下载 PNG
          </button>
        </div>
        <div className="toolbar">
          <label>
            指标
            <select
              value={settings.metric}
              onChange={(e) =>
                change({ metric: e.target.value, yLabel: e.target.value })
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
                  value={appearance[s.id]?.color || palette[i % palette.length]}
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
      <TablePanel ids={ids} history={history} notify={notify} />
    </>
  );
}
