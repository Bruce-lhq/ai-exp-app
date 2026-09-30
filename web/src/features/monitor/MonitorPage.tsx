import { useEffect, useMemo, useState } from "react";
import { Pause, Play, Square, GripVertical, RefreshCw, Trash2 } from "lucide-react";
import { api, items, type Run } from "../../app/api";
import { Empty, Modal } from "../../app/ui";
import { move } from "../parameters/values";
import {
  ExperimentChart,
  seriesColors,
  type Series,
  type ChartSettings,
} from "../analysis/ExperimentChart";
export const statusNames: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  stopped: "已停止",
  paused: "已暂停",
  starting: "启动中",
  stopping: "停止中",
  accepted: "已提交",
  external_running: "终端启动",
  external_exited: "进程已退出",
};
let lastRuns: Run[] = [];
let lastQueue: any = { runs: [], paused: false };
let lastPlot: { key: string; series: Series[] } | undefined;
export function MonitorPage({ notify }: { notify: (s: string) => void }) {
  const [runs, setRuns] = useState<Run[]>(lastRuns),
    [queue, setQueue] = useState<any>(lastQueue),
    [selected, setSelected] = useState(new URLSearchParams(location.search).get("run")||""),
    [log, setLog] = useState(""),
    [stop, setStop] = useState(""),
    [stopAction, setStopAction] = useState<"stop" | "pause">("stop"),
    [remove, setRemove] = useState(""),
    [pauseAlso, setPauseAlso] = useState(false),
    [drag, setDrag] = useState(0),
    [series, setSeries] = useState<Series[]>(lastPlot?.key === JSON.stringify(['val_ppl', []]) ? lastPlot.series : []),
    [metric, setMetric] = useState("val_ppl"),
    [title, setTitle] = useState(() => localStorage.getItem("monitor.title") || ""),
    [appearance, setAppearance] = useState<Record<string, { name?: string; color?: string; order?: number }>>(() => {
      try { return JSON.parse(localStorage.getItem("monitor.appearance") || "{}"); } catch { return {}; }
    }),
    [appearanceDrag, setAppearanceDrag] = useState("");
  const [history, setHistory] = useState<any[]>([]),
    [comparisons, setComparisons] = useState<string[]>([]);
  const [curveWarning, setCurveWarning] = useState("");
  const [curveLoading, setCurveLoading] = useState(true);
  async function refresh() {
    const [r, q] = await Promise.all([
      api("/api/runs", undefined, undefined, { background: true }),
      api("/api/queue", undefined, undefined, { background: true }),
    ]);
    lastRuns = items(r);
    lastQueue = q;
    setRuns(lastRuns);
    setQueue(q);
  }
  useEffect(() => {
    localStorage.setItem("monitor.title", title);
    localStorage.setItem("monitor.appearance", JSON.stringify(appearance));
  }, [title, appearance]);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try { await refresh(); } catch { /* Keep the last status during reconnect. */ }
      if (active) timer = setTimeout(poll, 3000);
    };
    void poll();
    api("/api/history")
      .then((x) => setHistory(items(x)))
      .catch(() => {});
    return () => { active = false; clearTimeout(timer); };
  }, []);
  const liveIdsKey = JSON.stringify(runs.filter((run) => ["running", "starting", "stopping", "external_running"].includes(run.status)).map((run) => run.id));
  useEffect(() => {
    let alive = true;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const liveIds: string[] = JSON.parse(liveIdsKey);
    const load = async () => {
      if (alive) setCurveLoading(true);
      try {
        const x = await api("/api/analysis/series", {
          history_ids: [...new Set([...liveIds, ...comparisons])], live_ids: liveIds, metric, x_axis: "tokens",
        }, undefined, { background: true, signal: controller.signal });
        if (alive) {
          setSeries(x.series || []);
          setCurveWarning((x.warnings || []).join("；"));
          lastPlot = { key: JSON.stringify([metric, comparisons]), series: x.series || [] };
        }
      } catch (e) {
        if (alive) setCurveWarning(`更新暂时失败，保留上次曲线：${(e as Error).message}`);
      }
      if (alive) setCurveLoading(false);
      if (alive) timer = setTimeout(load, 3000);
    };
    void load();
    return () => {
      alive = false;
      controller.abort();
      clearTimeout(timer);
    };
  }, [metric, JSON.stringify(comparisons), liveIdsKey]);
  useEffect(() => {
    if (!selected) return;
    let alive = true;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    setLog("");
    const load = async () => {
      try {
        const x = await api(`/api/runs/${selected}/log`, undefined, undefined, { background: true, signal: controller.signal });
        if (alive) setLog(typeof x === "string" ? x : x.text || x.log || "");
      } catch (e) {
        if (alive) setLog((previous) => previous || (e as Error).message);
      }
      if (alive) timer = setTimeout(load, 3000);
    };
    void load();
    return () => { alive = false; controller.abort(); clearTimeout(timer); };
  }, [selected]);
  async function action(fn: () => Promise<unknown>) {
    try {
      await fn();
      await refresh();
    } catch (e) {
      notify((e as Error).message);
    }
  }
  const settings = useMemo<ChartSettings>(() => ({
    metric,
    xAxis: "tokens",
    title,
    xLabel: "Trained tokens (B)",
    yLabel: metric,
    xScale: "linear",
    yScale: metric.toLowerCase().includes('ppl') ? "logarithmic" : "linear",
    width: 1536,
    height: 1044,
    pixelRatio: 1.5,
    xMin: 0,
    xMax: 10.75,
  }), [metric, title]);
  const orderedSeries = useMemo(() => [...series].sort((a, b) =>
    (appearance[a.id]?.order ?? series.indexOf(a)) - (appearance[b.id]?.order ?? series.indexOf(b)),
  ), [series, appearance]);
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">LIVE MONITOR</span>
          <h1>运行监控</h1>
          <p>运行留在云端。断开工作台，不会中断训练与队列。</p>
        </div>
        <div className="row">
        <button onClick={() => action(() => api("/api/connection/refresh", {}))}>
          <RefreshCw size={15} />
          刷新
        </button>
        </div>
      </div>
      <section className="panel live-chart-panel">
        <div className="panel-heading"><div><h3>当前运行曲线</h3><small className="muted">实时读取正在运行实验的指标</small></div><span className="count">{series.length}</span></div>
        <div className="toolbar">
          <label>指标 <input value={metric} onChange={(e) => setMetric(e.target.value)} list="monitor-metrics" /></label>
          <label>图标题 <input value={title} onChange={(e) => setTitle(e.target.value.trim())} /></label>
          <details><summary>历史对照（{comparisons.length}）</summary><button className="subtle" onClick={() => setComparisons(comparisons.length === history.length ? [] : history.map((h) => h.id))}>{comparisons.length === history.length ? "取消全选" : "全选"}</button>{history.map((h) => <label className="check" key={h.id}><input type="checkbox" checked={comparisons.includes(h.id)} onChange={(e) => setComparisons(e.target.checked ? [...comparisons, h.id] : comparisons.filter((id) => id !== h.id))} />{h.name || h.display_name}</label>)}</details>
          <datalist id="monitor-metrics"><option>val_ppl</option><option>train_ppl</option><option>R_min</option><option>R_mean</option><option>update_rms</option><option>train_loss</option></datalist>
        </div>
        {curveWarning && <p className="warning">{curveWarning}</p>}
        {series.length ? <ExperimentChart series={orderedSeries} settings={settings} appearance={appearance} /> : <Empty>{curveLoading ? <span role="status"><span className="spinner" /> 正在读取运行曲线…</span> : `当前没有可绘制的 ${metric} 数据`}</Empty>}
        {!!series.length && <details className="chart-appearance"><summary>编辑图例、顺序与配色</summary>{orderedSeries.map((s, i) => <div key={s.id} className="row" draggable onDragStart={() => setAppearanceDrag(s.id)} onDragOver={(e) => e.preventDefault()} onDrop={() => {
          const from = orderedSeries.findIndex((x) => x.id === appearanceDrag); if (from < 0 || from === i) return;
          const next = [...orderedSeries]; const [item] = next.splice(from, 1); next.splice(i, 0, item);
          setAppearance(Object.fromEntries(next.map((x, index) => [x.id, { ...appearance[x.id], order: index }])));
        }}><GripVertical size={14} /><input type="color" value={seriesColors(orderedSeries, appearance)[i]} onChange={(e) => {
          if (Object.entries(appearance).some(([id, value]) => id !== s.id && value.color?.toLowerCase() === e.target.value.toLowerCase())) { notify("每条曲线需要使用不同颜色"); return; }
          setAppearance((a) => ({ ...a, [s.id]: { ...a[s.id], color: e.target.value } }));
        }} /><input aria-label={`${s.name} 图例`} value={appearance[s.id]?.name ?? s.name} onChange={(e) => setAppearance((a) => ({ ...a, [s.id]: { ...a[s.id], name: e.target.value.trim() } }))} /></div>)}</details>}
      </section>
      <div className="monitor-grid">
        <section className="panel">
          <div className="panel-heading">
            <h3>实验</h3>
            <span className="count">{runs.length}</span>
          </div>
          {!runs.length ? (
            <Empty>在配置实验中启动或加入队列。</Empty>
          ) : (
            runs.map((r) => (
              <button
                className={`run-row ${selected === r.id ? "selected" : ""}`}
                key={r.id}
                onClick={() => setSelected(r.id)}
              >
                <span>
                  <strong>{r.display_name}</strong>
                  <small>
                    {r.gpu_ids?.length
                      ? `GPU ${r.gpu_ids.join(", ")}`
                      : "等待分配"}
                    {r.progress ? ` · ${r.progress}` : ""}
                    {r.remaining ? ` · 剩余 ${r.remaining}` : ""}
                    {r.queue_name && r.queue_name !== "-" ? ` · 队列 ${r.queue_name}` : ""}
                  </small>
                </span>
                <span className={`status ${r.status}`}>
                  {statusNames[r.status] || r.status}
                </span>
              </button>
            ))
          )}
        </section>
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h3>
                等待队列{" "}
                <span className="count">{queue.runs?.length || 0}</span>
              </h3>
              <small className="muted">严格顺序 · 拖动调整优先级</small>
            </div>
            <button
              onClick={() =>
                action(() =>
                  api(`/api/queue/${queue.paused ? "resume" : "pause"}`, {}),
                )
              }
            >
              {queue.paused ? <Play size={14} /> : <Pause size={14} />}{" "}
              {queue.paused ? "恢复队列" : "暂停队列"}
            </button>
          </div>
          {queue.paused && (
            <p className="warning">队列已暂停，运行中的实验继续。</p>
          )}
          {queue.runs?.length ? (
            queue.runs.map((r: Run, i: number) => (
              <div
                className="queue-row"
                draggable
                key={r.id}
                onDragStart={() => setDrag(i)}
                onDragOver={(e) => e.preventDefault()}
                onDrop={() =>
                  action(() =>
                    api(
                      "/api/queue/order",
                      {
                        run_ids: move(queue.runs, drag, i).map(
                          (x: any) => x.id,
                        ),
                        revision: queue.revision,
                      },
                      "PUT",
                    ),
                  )
                }
              >
                <GripVertical size={16} />
                <span className="queue-position">{i + 1}</span>
                <strong>{r.display_name}</strong>
                <span>{r.parameters?.runtime?.gpu_count || 1} GPU</span>
                <button
                  className="subtle"
                  onClick={() =>
                    action(() => api(`/api/queue/${r.id}`, {}, "DELETE"))
                  }
                >
                  移出
                </button>
              </div>
            ))
          ) : (
            <Empty>等待队列为空</Empty>
          )}
        </section>
      </div>
      {selected && (
        <section className="panel run-detail">
          <div className="panel-heading">
            <h3>{runs.find((x) => x.id === selected)?.display_name}</h3>
            <div className="row">
              {["running", "starting"].includes(
                runs.find((x) => x.id === selected)?.status || "",
              ) && (
                <>
                <button onClick={() => { setStopAction("pause"); setPauseAlso(false); setStop(selected); }}><Pause size={14} />暂停实验</button>
                <button className="danger" onClick={() => { setStopAction("stop"); setPauseAlso(false); setStop(selected); }}>
                  <Square size={14} />
                  停止实验
                </button>
                </>
              )}
              {runs.find((x) => x.id === selected)?.status === "external_running" && (runs.find((x) => x.id === selected)?.adopted
                ? <button onClick={() => { setStopAction('pause'); setPauseAlso(false); setStop(selected); }}><Pause size={14} />暂停实验</button>
                : <button onClick={() => action(async () => { await api(`/api/runs/${selected}/adopt`, {}); notify('进程身份已验证并接管，训练继续运行'); })}>接管进程</button>)}
              {["paused", "stopped", "failed", "completed", "external_exited"].includes(runs.find((x) => x.id === selected)?.status || "") && (
                <button className="danger" onClick={() => setRemove(selected)}><Trash2 size={14} />删除记录</button>
              )}
            </div>
          </div>
          <details open>
            <summary>实时日志</summary>
            <pre className="log">{log || "等待日志…"}</pre>
          </details>
        </section>
      )}
      {stop && (
        <Modal title={stopAction === "pause" ? "暂停实验？" : "停止实验？"} close={() => setStop("")}>
          <p>当前训练进程将退出并释放 GPU，不额外保存 checkpoint。最近 checkpoint 之后的进度需要重跑。</p>
          {runs.find((r) => r.id === stop)?.external && <p className="warning">暂停后可在历史管理中载入续跑到编辑区。外部启动脚本的后续任务不会由工作台暂停。</p>}
          {!runs.find((r) => r.id === stop)?.external && <label className="check">
            <input
              type="checkbox"
              checked={pauseAlso}
              onChange={(e) => setPauseAlso(e.target.checked)}
            />
            同时暂停后续队列
          </label>}
          <footer>
            <button onClick={() => setStop("")}>取消</button>
            <button
              className="danger"
              onClick={() =>
                action(async () => {
                  await api(`/api/runs/${stop}/${stopAction}`, {
                    confirmed: true,
                    pause_queue: pauseAlso,
                  });
                  setStop("");
                  notify(stopAction === "pause" ? "已请求暂停实验，正在等待进程退出" : "已请求停止实验");
                })
              }
            >
              {stopAction === "pause" ? "确认暂停" : "确认停止"}
            </button>
          </footer>
        </Modal>
      )}
      {remove && (
        <Modal title="删除监控记录？" close={() => setRemove("")}>
          <p>从运行监控中移除此实验。历史记录、本地缓存和云端文件均保留；需要续跑时仍可在历史管理中载入续跑到编辑区。</p>
          <footer>
            <button onClick={() => setRemove("")}>取消</button>
            <button
              className="danger"
              onClick={() =>
                action(async () => {
                  await api(`/api/runs/${remove}/remove`, { confirmed: true });
                  setRemove("");
                  if (selected === remove) setSelected("");
                  notify("已删除监控记录，历史和实验文件均保留");
                })
              }
            >
              确认删除记录
            </button>
          </footer>
        </Modal>
      )}
    </>
  );
}
