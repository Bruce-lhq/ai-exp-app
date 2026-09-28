import { useEffect, useState } from "react";
import {
  Download,
  FolderInput,
  RefreshCw,
  Archive,
  Trash2,
} from "lucide-react";
import { api, items, type Parameters } from "../../app/api";
import { DirectoryPicker, Empty, Modal } from "../../app/ui";
import { statusNames } from "../monitor/MonitorPage";
export function HistoryPage({
  notify,
  onLoad,
}: {
  notify: (s: string) => void;
  onLoad: (p: Parameters) => void;
}) {
  const [history, setHistory] = useState<any[]>([]),
    [source, setSource] = useState(""),
    [filter, setFilter] = useState(""),
    [archived, setArchived] = useState(false),
    [deletion, setDeletion] = useState<any>(null),
    [selected, setSelected] = useState<string[]>([]);
  async function refresh() {
    setHistory(items(await api("/api/history")));
  }
  useEffect(() => {
    refresh().catch((e) => notify(e.message));
    const t = setInterval(() => refresh().catch(() => {}), 10000);
    return () => clearInterval(t);
  }, []);
  async function action(fn: () => Promise<unknown>) {
    try {
      await fn();
      await refresh();
    } catch (e) {
      notify((e as Error).message);
    }
  }
  const shown = history.filter(
    (h) =>
      (archived || h.visibility !== "archived") &&
      `${h.name || h.display_name} ${(h.tags || []).join(" ")} ${h.notes || ""}`
        .toLowerCase()
        .includes(filter.toLowerCase()),
  );
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">EXPERIMENT ARCHIVE</span>
          <h1>历史管理</h1>
          <p>手动导入已有实验。平台实验结束后自动同步到本地。</p>
        </div>
        <div className="row">
          <button onClick={() => setSource("local")}>
            <FolderInput size={16} />
            从本地导入
          </button>
          <button className="primary" onClick={() => setSource("remote")}>
            <FolderInput size={16} />
            从云端导入
          </button>
          <button onClick={() => action(async () => { const result = await api("/api/history/sync-running", {}, "POST"); notify(`已更新 ${result.count || 0} 个正在运行的实验`); })}>
            <RefreshCw size={16} />
            拉取正在运行实验
          </button>
        </div>
      </div>
      <section className="panel">
        <div className="toolbar">
          <input
            placeholder="搜索实验名称、标签或备注"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <label className="check">
            <input
              type="checkbox"
              checked={archived}
              onChange={(e) => setArchived(e.target.checked)}
            />
            显示已归档
          </label>
          <button onClick={() => action(refresh)}>
            <RefreshCw size={14} />
            刷新
          </button>
          {selected.length > 0 && (
            <button
              onClick={() => {
                for (const id of selected) {
                  const a = document.createElement("a");
                  a.href = `/api/history/${id}/export`;
                  a.click();
                }
              }}
            >
              <Download size={14} />
              导出所选 ({selected.length})
            </button>
          )}
        </div>
        {!shown.length ? (
          <Empty>
            <Archive size={30} />
            <h3>还没有历史实验</h3>
            <p>从目录导入日志、指标和参数，即可离线查看与比较。</p>
          </Empty>
        ) : (
          <div className="history-list">
            {shown.map((h) => (
              <article className="history-card" key={h.id}>
                <div className="history-title">
                  <input
                    type="checkbox"
                    aria-label={`选择 ${h.name}`}
                    checked={selected.includes(h.id)}
                    onChange={(e) =>
                      setSelected(
                        e.target.checked
                          ? [...selected, h.id]
                          : selected.filter((id) => id !== h.id),
                      )
                    }
                  />
                  <div>
                    <button
                      className="text-button"
                      title="重命名实验"
                      onClick={() =>
                        action(async () => {
                          const name = prompt(
                            "实验名称",
                            h.name || h.display_name,
                          );
                          if (name)
                            await api(
                              `/api/history/${h.id}`,
                              { name },
                              "PATCH",
                            );
                        })
                      }
                    >
                      <h3>{h.name || h.display_name}</h3>
                    </button>
                    <small className="muted">
                      {h.source?.path || h.source_path || h.path || h.remote_path || "本地缓存"}
                    </small>
                  </div>
                  <span className={`status ${h.status}`}>
                    {statusNames[h.status] || h.status || "已导入"}
                  </span>
                  <span className="sync-label">
                    {h.sync_status || "已缓存"}
                  </span>
                </div>
                <div className="history-meta">
                  <button
                    className="tag"
                    onClick={() =>
                      action(async () => {
                        const tags = prompt(
                          "标签，用逗号分隔",
                          (h.tags || []).join(", "),
                        );
                        if (tags !== null)
                          await api(
                            `/api/history/${h.id}`,
                            {
                              tags: tags
                                .split(/[,，]/)
                                .map((x) => x.trim())
                                .filter(Boolean),
                            },
                            "PATCH",
                          );
                      })
                    }
                  >
                    {h.tags?.join(" · ") || "＋添加标签"}
                  </button>
                  <button
                    className="text-button muted"
                    onClick={() =>
                      action(async () => {
                        const notes = prompt("实验备注", h.notes || "");
                        if (notes !== null)
                          await api(`/api/history/${h.id}`, { notes }, "PATCH");
                      })
                    }
                  >
                    {h.notes || "添加实验备注"}
                  </button>
                </div>
                <div className="history-actions">
                  <button
                    disabled={!h.parameters}
                    onClick={() => onLoad(h.parameters)}
                  >
                    载入参数到编辑区
                  </button>
                  <a className="button" href={`/api/history/${h.id}/export`}>
                    <Download size={14} />
                    导出实验
                  </a>
                  <button
                    onClick={() =>
                      action(() => api("/api/history/import", {source:h.source,name:h.name}))
                    }
                  >
                    同步最终文件
                  </button>
                  <button
                    onClick={() =>
                      action(() =>
                        api(
                          `/api/history/${h.id}`,
                          { archived: h.visibility !== "archived" },
                          "PATCH",
                        ),
                      )
                    }
                  >
                    {h.visibility === "archived" ? "恢复显示" : "归档隐藏"}
                  </button>
                  <button
                    onClick={() =>
                      action(async () => {
                        if (
                          confirm("从历史列表移除？文件保留，以后可重新导入。")
                        )
                          await api(
                            `/api/history/${h.id}`,
                            undefined,
                            "DELETE",
                          );
                      })
                    }
                  >
                    从历史移除
                  </button>
                  <button
                    className="danger subtle"
                    title="永久删除缓存文件"
                    onClick={() =>
                      action(async () => {
                        const scope=h.source?.kind==='remote'?prompt('删除范围：输入 local（本地缓存）、remote（远端文件）或 both（两处）','local'):'local';
                        if(!scope || !['local','remote','both'].includes(scope))return;
                        const preview = await api(
                          `/api/history/${h.id}/delete-preview`,
                          { scope },
                        );
                        setDeletion({ ...preview, id: h.id, name: h.name });
                      })
                    }
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
      {source && (
        <DirectoryPicker
          source={source}
          onSelect={(path) =>
            action(async () => {
              await api("/api/history/import", { source, path, alias: "gpu" });
              setSource("");
              notify("实验已导入历史");
            })
          }
          close={() => setSource("")}
        />
      )}{" "}
      {deletion && (
        <Modal title="永久删除文件" close={() => setDeletion(null)}>
          <p>将永久删除「{deletion.name}」的以下文件，无法撤销。</p>
          <pre>
            {(deletion.targets || [])
              .map((x: any) => (typeof x === "string" ? x : JSON.stringify(x)))
              .join("\n")}
          </pre>
          <footer>
            <button onClick={() => setDeletion(null)}>取消</button>
            <button
              className="danger"
              onClick={() =>
                action(async () => {
                  await api(`/api/history/${deletion.id}/delete-confirm`, {
                    confirmation_token: deletion.confirmation_token,
                  });
                  setDeletion(null);
                  notify("文件已删除");
                })
              }
            >
              确认永久删除
            </button>
          </footer>
        </Modal>
      )}
    </>
  );
}
