import { useEffect, useState } from "react";
import { Pause, Play, Square, GripVertical, RefreshCw } from "lucide-react";
import { api, items, type Run } from "../../app/api";
import { Empty, Modal } from "../../app/ui";
import { move } from "../parameters/values";
import {
  ExperimentChart,
  palette,
  type Series,
  type ChartSettings,
} from "../analysis/ExperimentChart";
export const statusNames: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  stopped: "已停止",
  starting: "启动中",
  stopping: "停止中",
  accepted: "已提交",
  external_running: "终端启动",
};
export function MonitorPage({ notify }: { notify: (s: string) => void }) {
  const [runs, setRuns] = useState<Run[]>([]),
    [queue, setQueue] = useState<any>({ runs: [], paused: false }),
    [selected, setSelected] = useState(new URLSearchParams(location.search).get("run")||""),
    [log, setLog] = useState(""),
    [stop, setStop] = useState(""),
    [pauseAlso, setPauseAlso] = useState(false),
    [drag, setDrag] = useState(0),
    [series, setSeries] = useState<Series[]>([]),
    [metric, setMetric] = useState("val_ppl"),
    [title, setTitle] = useState(() => localStorage.getItem("monitor.title") || ""),
    [appearance, setAppearance] = useState<Record<string, { name?: string; color?: string; order?: number }>>(() => {
      try { return JSON.parse(localStorage.getItem("monitor.appearance") || "{}"); } catch { return {}; }
    }),
    [appearanceDrag, setAppearanceDrag] = useState("");
  const [history, setHistory] = useState<any[]>([]),
    [comparisons, setComparisons] = useState<string[]>([]);
  async function refresh() {
    const [r, q, g] = await Promise.all([
      api("/api/runs"),
      api("/api/queue"),
      Promise.resolve([]),
    ]);
    setRuns(items(r));
    setQueue(q);
    void g;
  }
  useEffect(() => {
    localStorage.setItem("monitor.title", title);
    localStorage.setItem("monitor.appearance", JSON.stringify(appearance));
  }, [title, appearance]);
  useEffect(() => {
    refresh().catch((e) => notify(e.message));
    api("/api/history")
      .then((x) => setHistory(items(x)))
      .catch(() => {});
    const t = setInterval(() => refresh().catch(() => {}), 5000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => {
    let alive = true;
    const load = () => {
      const liveIds = runs.filter((run) => ["running", "starting", "stopping", "external_running"].includes(run.status)).map((run) => run.id);
      api("/api/analysis/series", {
        history_ids: [...liveIds, ...comparisons], metric, x_axis: "tokens",
      }).then((x) => { if (alive) setSeries(x.series || []); }).catch(() => { if (alive) setSeries([]); });
      if (!selected) return;
      api(`/api/runs/${selected}/log`)
        .then((x) => {
          if (alive) setLog(typeof x === "string" ? x : x.text || x.log || "");
        })
        .catch((e) => {
          if (alive) setLog(e.message);
        });
    };
    load();
    const t = setInterval(load, 5000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [selected, metric, comparisons, runs]);
  async function action(fn: () => Promise<unknown>) {
    try {
      await fn();
      await refresh();
    } catch (e) {
      notify((e as Error).message);
    }
  }
  const settings: ChartSettings = {
    metric,
    xAxis: "tokens",
    title,
    xLabel: "训练 tokens",
    yLabel: metric,
    xScale: "linear",
    yScale: "logarithmic",
    width: 1200,
    height: 600,
    pixelRatio: 2,
  };
  const orderedSeries = [...series].sort((a, b) =>
    (appearance[a.id]?.order ?? series.indexOf(a)) - (appearance[b.id]?.order ?? series.indexOf(b)),
  );
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">LIVE MONITOR</span>
          <h1>运行监控</h1>
          <p>运行留在云端。断开工作台，不会中断训练与队列。</p>
        </div>
        <button onClick={() => action(refresh)}>
          <RefreshCw size={15} />
          刷新
        </button>
      </div>
      <section className="panel live-chart-panel">
        <div className="panel-heading"><div><h3>当前运行曲线</h3><small className="muted">实时读取正在运行实验的指标</small></div><span className="count">{series.length}</span></div>
        <div className="toolbar">
          <label>指标 <input value={metric} onChange={(e) => setMetric(e.target.value)} list="monitor-metrics" /></label>
          <label>图标题 <input value={title} onChange={(e) => setTitle(e.target.value.trim())} /></label>
          <details><summary>历史对照（{comparisons.length}）</summary><button className="subtle" onClick={() => setComparisons(comparisons.length === history.length ? [] : history.map((h) => h.id))}>{comparisons.length === history.length ? "取消全选" : "全选"}</button>{history.map((h) => <label className="check" key={h.id}><input type="checkbox" checked={comparisons.includes(h.id)} onChange={(e) => setComparisons(e.target.checked ? [...comparisons, h.id] : comparisons.filter((id) => id !== h.id))} />{h.name || h.display_name}</label>)}</details>
          <datalist id="monitor-metrics"><option>val_ppl</option><option>train_ppl</option><option>train_loss</option></datalist>
        </div>
        {series.length ? <ExperimentChart series={orderedSeries} settings={settings} appearance={appearance} /> : <Empty>当前没有可绘制的 {metric} 数据</Empty>}
        {!!series.length && <details className="chart-appearance"><summary>编辑图例、顺序与配色</summary>{orderedSeries.map((s, i) => <div key={s.id} className="row" draggable onDragStart={() => setAppearanceDrag(s.id)} onDragOver={(e) => e.preventDefault()} onDrop={() => {
          const from = orderedSeries.findIndex((x) => x.id === appearanceDrag); if (from < 0 || from === i) return;
          const next = [...orderedSeries]; const [item] = next.splice(from, 1); next.splice(i, 0, item);
          setAppearance(Object.fromEntries(next.map((x, index) => [x.id, { ...appearance[x.id], order: index }])));
        }}><GripVertical size={14} /><input type="color" value={appearance[s.id]?.color || palette[i % palette.length]} onChange={(e) => {
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
                <button className="danger" onClick={() => setStop(selected)}>
                  <Square size={14} />
                  停止实验
                </button>
              )}
              {runs.find((x) => x.id === selected)?.status === "external_running" && <span className="muted">由终端启动，工作台仅监控</span>}
              {["stopped", "failed"].includes(
                runs.find((x) => x.id === selected)?.status || "",
              ) && (
                <button
                  onClick={() =>
                    action(() => api(`/api/runs/${selected}/resume`, {}))
                  }
                >
                  <Play size={14} />
                  严格续跑
                </button>
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
        <Modal title="停止实验？" close={() => setStop("")}>
          <p>训练将停止。以后可从最近已有的完整 checkpoint 严格续跑。</p>
          <label className="check">
            <input
              type="checkbox"
              checked={pauseAlso}
              onChange={(e) => setPauseAlso(e.target.checked)}
            />
            同时暂停后续队列
          </label>
          <footer>
            <button onClick={() => setStop("")}>取消</button>
            <button
              className="danger"
              onClick={() =>
                action(async () => {
                  await api(`/api/runs/${stop}/stop`, {
                    confirmed: true,
                    pause_queue: pauseAlso,
                  });
                  setStop("");
                  notify("已请求停止实验");
                })
              }
            >
              确认停止
            </button>
          </footer>
        </Modal>
      )}
    </>
  );
}
