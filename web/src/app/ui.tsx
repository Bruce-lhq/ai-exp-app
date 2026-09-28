import { useState, type ReactNode } from "react";
import { X, Folder, ChevronRight, ArrowUp } from "lucide-react";
import { api, items } from "./api";
export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}
export function Modal({
  title,
  children,
  close,
}: {
  title: string;
  children: ReactNode;
  close: () => void;
}) {
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="modal"
      >
        <header>
          <h2>{title}</h2>
          <button className="icon" aria-label="关闭" onClick={close}>
            <X size={18} />
          </button>
        </header>
        {children}
      </section>
    </div>
  );
}
export function DirectoryPicker({
  source = "remote",
  host = "gpu",
  initial = "/",
  onSelect,
  close,
}: {
  source?: string;
  host?: string;
  initial?: string;
  onSelect: (path: string) => void;
  close: () => void;
}) {
  const [path, setPath] = useState(initial),
    [entries, setEntries] = useState<any[]>([]),
    [error, setError] = useState(""),
    [loaded, setLoaded] = useState(false);
  async function browse(value: string) {
    try {
      const d = await api(
        `/api/${source === "local" ? "local" : "remote"}/browse`,
        { path: value, host },
      );
      setPath(d.path || value);
      setEntries(items(d, "entries"));
      setLoaded(true);
      setError("");
    } catch (e) {
      setError(String(e));
    }
  }
  return (
    <Modal
      title={source === "local" ? "选择本地目录" : "选择云端 GPU 目录"}
      close={close}
    >
      <form
        className="row"
        onSubmit={(e) => {
          e.preventDefault();
          browse(path);
        }}
      >
        <button
          type="button"
          className="icon"
          aria-label="上级目录"
          onClick={() => browse(path.replace(/\/[^/]+\/?$/, "") || "/")}
        >
          <ArrowUp size={17} />
        </button>
        <input
          aria-label="目录路径"
          value={path}
          onChange={(e) => setPath(e.target.value)}
        />
        <button>打开</button>
      </form>
      {error && <p className="warning">{error}</p>}
      <div className="directory-list">
        {!loaded ? (
          <Empty>输入目录路径，点击打开以浏览文件夹。</Empty>
        ) : (
          entries
            .filter((x) => x.is_dir !== false && x.type !== "file")
            .map((x) => (
              <button
                key={x.path || x.name}
                onClick={() =>
                  browse(x.path || `${path.replace(/\/$/, "")}/${x.name}`)
                }
              >
                <Folder size={17} />
                <span>{x.name}</span>
                <ChevronRight size={15} />
              </button>
            ))
        )}
      </div>
      <footer>
        <button className="primary" onClick={() => onSelect(path)}>
          选择此目录
        </button>
      </footer>
    </Modal>
  );
}
