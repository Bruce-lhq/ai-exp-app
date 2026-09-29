import { useEffect, useState, useRef } from "react";
import {
  SlidersHorizontal,
  Activity,
  Archive,
  ChartNoAxesCombined,
  FlaskConical,
  Check,
  X,
  Bell,
} from "lucide-react";
import { api, type Parameters } from "./api";
import { ParameterPage } from "../features/parameters/ParameterPage";
import { MonitorPage } from "../features/monitor/MonitorPage";
import { HistoryPage } from "../features/history/HistoryPage";
import { AnalysisPage } from "../features/analysis/AnalysisPage";
export default function App() {
  const [page, setPage] = useState("monitor"),
    [message, setMessage] = useState(""),
    [connection, setConnection] = useState<any>({ connected: false }),
    [historical, setHistorical] = useState<Parameters | null>(null);
  const [loading, setLoading] = useState(0);
  const [configureVisited, setConfigureVisited] = useState(false);
  useEffect(() => {
    if (page === "configure") setConfigureVisited(true);
  }, [page]);
  const [notices,setNotices]=useState<any[]>([]),[noticeOpen,setNoticeOpen]=useState(false);
  const seen=useRef(new Set<string>());
  const notify = (m: string) => setMessage(m);
  useEffect(()=>{
    const poll=()=>api<any[]>("/api/notifications").then(list=>{
      setNotices(list);
      for(const n of list){if(n.read||seen.current.has(n.id))continue;seen.current.add(n.id);
        setMessage(`${n.title}：${n.body}`);
      }
    }).catch(()=>{});
    poll();const t=setInterval(poll,10000);return()=>clearInterval(t);
  },[]);
  useEffect(() => {
    const handler = (event: Event) => setLoading((value) => Math.max(0, value + Number((event as CustomEvent).detail || 0)));
    window.addEventListener("ai-exp-loading", handler);
    return () => window.removeEventListener("ai-exp-loading", handler);
  }, []);
  useEffect(() => {
    const check = () =>
      api("/api/connection")
        .then(setConnection)
        .catch(() =>
          setConnection({ connected: false, error: "本地服务暂时不可用" }),
        );
    check();
    const t = setInterval(check, 10000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => {
    if (!message) return;
    const t = setTimeout(() => setMessage(""), 7000);
    return () => clearTimeout(t);
  }, [message]);
  const nav = [
    { id: "configure", name: "配置实验", icon: SlidersHorizontal },
    { id: "monitor", name: "运行监控", icon: Activity },
    { id: "history", name: "历史管理", icon: Archive },
    { id: "analysis", name: "画图与列表", icon: ChartNoAxesCombined },
  ];
  return (
    <div className="app">
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setPage("configure");
          }}
        >
          <span>
            <FlaskConical size={23} />
          </span>
          <div>
            实验工作台<small>AI EXPERIMENTS</small>
          </div>
        </a>
        <nav aria-label="工作区">
          {nav.map((n) => (
            <button
              key={n.id}
              className={page === n.id ? "active" : ""}
              onClick={() => setPage(n.id)}
            >
              <n.icon size={19} />
              {n.name}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <span className="local-mark">LOCAL WORKSPACE</span>
          <p>
            代码快照 · 参数留存
            <br />
            实验与结果，一处管理
          </p>
          <div className="version">
            个人工作台 <span>v0.1</span>
          </div>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <span>
            工作空间 <span className="breadcrumb">/</span>{" "}
            {nav.find((n) => n.id === page)?.name}
          </span>
          <div className="row">
            <span
              title={connection.error || "SSH 连接正常"}
              className="connection"
            >
              <i className={connection.connected ? "online" : ""} />
              {connection.connected ? "GPU 已连接" : "GPU 未连接"}
            </span>
            <button
              className="icon"
              title="实验通知"
              aria-label="实验通知"
              onClick={()=>setNoticeOpen(!noticeOpen)}
            ><Bell size={17}/>{notices.filter(n=>!n.read).length>0&&<span className="count">{notices.filter(n=>!n.read).length}</span>}
            </button>
          </div>
        </header>
        {noticeOpen&&<section className="panel notifications"><div className="panel-heading"><h3>实验通知</h3><button onClick={async()=>{try{if("Notification" in window){const p=await Notification.requestPermission();notify(p==='granted'?'系统通知已启用':'系统通知未授权')}}catch(e){notify((e as Error).message)}}}>启用系统通知</button></div>{notices.length?notices.map(n=><button className="run-row" key={n.id} onClick={async()=>{try{await api(`/api/notifications/${n.id}/read`,{});setNotices(ns=>ns.map(x=>x.id===n.id?{...x,read:true}:x));history.replaceState(null,'',`?run=${encodeURIComponent(n.run_id)}`);setPage('monitor');setNoticeOpen(false)}catch(e){notify((e as Error).message)}}}><span><strong>{n.title}</strong><small>{n.body}</small></span><span>{n.read?'已读':'未读'}</span></button>):<p className="empty">暂无实验通知</p>}</section>}
        <main>
          {(page === "configure" || configureVisited) && <div hidden={page !== "configure"}>
            <ParameterPage
              notify={notify}
              onRun={() => setPage("monitor")}
              historical={historical}
              onHistoricalLoaded={() => setHistorical(null)}
            />
          </div>}
          {page === "monitor" && <MonitorPage notify={notify} />}{" "}
          {page === "history" && (
            <HistoryPage
              notify={notify}
              onLoad={(p) => {
                setHistorical(p);
                setPage("configure");
              }}
            />
          )}
          {page === "analysis" && <AnalysisPage notify={notify} />}
        </main>
      </div>
      {message && (
        <div role="status" className="toast">
          <Check size={17} />
          <span>{message}</span>
          <button
            className="icon"
            aria-label="关闭提醒"
            onClick={() => setMessage("")}
          >
            <X size={16} />
          </button>
        </div>
      )}
      {page !== "analysis" && loading > 0 && <div className="loading-overlay" role="status" aria-label="正在加载"><span className="spinner" /> 正在加载…</div>}
    </div>
  );
}
