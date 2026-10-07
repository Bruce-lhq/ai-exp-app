import { useEffect, useRef, useState } from "react";
import { Cloud, RefreshCw } from "lucide-react";
import { api } from "./api";
import { Modal } from "./ui";

type Status = {
  mode: "off" | "hub" | "client";
  state: "idle" | "syncing" | "offline" | "conflict";
  port?: number;
  revision?: number | string;
  last_synced?: string;
  error?: string;
  pending?: number;
  local_only_count?: number;
  other_host_count?: number;
  conflicts?: { id: string; kind: string; name?: string; local: unknown; remote: unknown }[];
};
const labels = { idle: "已同步", syncing: "同步中", offline: "等待连接", conflict: "需处理冲突" };
export function WorkspaceSync({ notify }: { notify: (message: string) => void }) {
  const [status, setStatus] = useState<Status>();
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<Status["mode"]>("off");
  const [port, setPort] = useState(8765);
  const [busy, setBusy] = useState(false);
  const revision = useRef<Status["revision"]>(undefined);
  async function refresh() {
    const next = await api<Status>("/api/workspace-sync", undefined, undefined, { background: true });
    if (!next.mode) return;
    setStatus(next);
    if (revision.current !== undefined && next.revision !== revision.current) {
      window.dispatchEvent(new Event("workspace-sync-changed"));
    }
    revision.current = next.revision;
  }
  useEffect(() => {
    refresh().catch(() => {});
    const timer = setInterval(() => refresh().catch(() => {}), 10000);
    return () => clearInterval(timer);
  }, []);
  async function act(work: () => Promise<unknown>) {
    setBusy(true);
    try { await work(); await refresh(); }
    catch (error) { notify((error as Error).message); }
    finally { setBusy(false); }
  }
  const title = status?.mode && status.mode !== "off" ? labels[status.state] || "跨设备同步" : "跨设备同步";
  return <>
    <button className="icon" title={title} aria-label="跨设备同步" onClick={() => {
      setMode(status?.mode || "off"); setPort(status?.port || 8765); setOpen(true);
    }}><Cloud size={17} />{status?.state === "conflict" && <span className="count">!</span>}</button>
    {open && <Modal title="跨设备同步" close={() => setOpen(false)}>
      <p>同步项目、参数组、历史管理、表格模板与图表设置。本地缓存与网络设置保留在各设备；离线修改会在重新连接后同步。</p>
      <form onSubmit={event => { event.preventDefault(); void act(async () => {
        await api("/api/workspace-sync/settings", { mode, port }, "PUT", { background: true });
        notify("同步设置已保存");
      }); }}>
        <div className="local-settings-fields">
          <label className="local-setting-field">同步方式<select aria-label="同步方式" value={mode} onChange={event => setMode(event.target.value as Status["mode"])}>
            <option value="off">关闭</option><option value="hub">云端共享工作空间</option><option value="client">与云端同步</option>
          </select></label>
          <label className="local-setting-field">云端网页端口<input aria-label="云端网页端口" type="number" min={1} max={65535} value={port} onChange={event => setPort(Number(event.target.value))} required /></label>
        </div>
        <p role="status">{status?.mode === "off" ? "未启用同步" : title}{status?.pending ? ` · ${status.pending} 项待同步` : ""}{status?.last_synced ? ` · 上次同步 ${new Date(status.last_synced).toLocaleString()}` : ""}</p>
        {status?.error && <p className="warning" role="alert">{status.error}</p>}
        {!!status?.local_only_count && <p>{status.local_only_count} 个从本地目录导入的实验保留在当前后台；跨设备历史同步仅包含云端来源。实验文件缓存仍需在历史管理更新。</p>}
        {!!status?.other_host_count && <p>{status.other_host_count} 项其他 SSH 主机的项目或历史保留在本端；当前同步中心对应工作空间设置中的主机。</p>}
        <footer><button type="button" disabled={busy || status?.mode === "off"} onClick={() => void act(() => api("/api/workspace-sync/refresh", {}, undefined, { background: true }))}><RefreshCw size={15} />立即同步</button><button className="primary" disabled={busy} type="submit">保存设置</button></footer>
      </form>
      {(status?.conflicts || []).map(conflict => <section className="panel" key={conflict.id}>
        <h3>{conflict.name || conflict.kind}</h3><p>两端同时修改了这项内容，请选择保留的版本。</p>
        <details><summary>查看两个版本</summary><p>本机</p><pre>{JSON.stringify(conflict.local, null, 2)}</pre><p>云端</p><pre>{JSON.stringify(conflict.remote, null, 2)}</pre></details>
        <div className="row">{(["local", "remote"] as const).map(choice => <button key={choice} disabled={busy} onClick={() => void act(async () => {
          await api(`/api/workspace-sync/conflicts/${encodeURIComponent(conflict.id)}`, { choice }, undefined, { background: true });
          window.dispatchEvent(new Event("workspace-sync-changed"));
        })}>{choice === "local" ? "保留本机" : "保留云端"}</button>)}</div>
      </section>)}
    </Modal>}
  </>;
}
