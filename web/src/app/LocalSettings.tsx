import { useState } from "react";
import { api } from "./api";
import { Modal } from "./ui";

export type LocalSettings = Record<string, string>;
export type SettingsResponse = { local_settings: LocalSettings; configured: boolean };

const fields = [
  ["ssh_alias", "SSH 主机别名"],
  ["remote_root", "云端工作台目录"],
  ["remote_projects_root", "云端代码目录"],
  ["remote_runs_root", "云端实验目录"],
  ["remote_data_root", "云端数据目录"],
  ["local_import_root", "本地实验导入目录"],
] as const;
const advancedFields = [
  ["remote_agent", "云端代理路径"],
  ["remote_python", "云端 Python"],
  ["remote_state_dir", "云端状态目录"],
  ["remote_groups_root", "云端实验组目录"],
  ["remote_import_root", "云端导入起始目录"],
] as const;
const requiredFields = new Set(["ssh_alias", "remote_agent", "remote_python", "remote_runs_root"]);

export function LocalSettingsDialog({ initial, firstRun, close, notify }: {
  initial: LocalSettings;
  firstRun: boolean;
  close: () => void;
  notify: (message: string) => void;
}) {
  const [draft, setDraft] = useState(initial), [saving, setSaving] = useState(false), [error, setError] = useState("");
  const localMode = draft.connection_mode === "local";
  const input = ([key, originalTitle]: readonly [string, string]) => {
    const title = localMode && key === "ssh_alias" ? "代理主机标识" : originalTitle;
    return (
    <label key={key} className="local-setting-field">
      {title}{(requiredFields.has(key) || localMode && key === "remote_state_dir") && " *"}
      <input aria-label={title} value={draft[key] || ""} onChange={(event) => setDraft({ ...draft, [key]: event.target.value })} />
    </label>
  );
  };
  return <Modal title={firstRun ? "设置工作空间" : "工作空间设置"} close={close}>
    <p>{localMode ? "工作台直接使用所在 GPU 的实验代理与现有队列，不再 SSH 登录自己。代理主机标识须与现有配置一致。" : "填写后台所在电脑使用的 SSH 主机和目录。设置保存在后台工作空间；稍后设置也可以查看缓存历史、画图和列表。"}</p>
    <p>“本地”目录指工作台后台所在电脑的目录。部署在 GPU 时，本地导入也浏览 GPU 文件，不是 iPhone 文件夹。</p>
    <p>* 为运行实验所需；实验目录请填写绝对路径；数据目录仅在训练项目需要时填写。{localMode && "本机模式的 Python、代理和状态目录均须为绝对路径，状态目录必须复用现有代理目录。"}</p>
    <form onSubmit={async (event) => {
      event.preventDefault();
      setSaving(true);
      setError("");
      try {
        await api<SettingsResponse>("/api/settings/local", Object.fromEntries(Object.entries(draft).map(([key, value]) => [key, value.trim()])), "PUT");
        notify("工作空间设置已保存");
        close();
      } catch (failure) { setError((failure as Error).message); }
      finally { setSaving(false); }
    }}>
      <div className="local-settings-fields"><label className="local-setting-field">连接方式<select aria-label="连接方式" value={draft.connection_mode || "ssh"} onChange={(event) => setDraft({ ...draft, connection_mode: event.target.value })}><option value="ssh">SSH 远端</option><option value="local">本机 GPU 代理</option></select></label>{fields.map(input)}</div>
      <details className="local-settings-advanced"><summary>高级设置</summary><div className="local-settings-fields">{advancedFields.map(input)}</div></details>
      {error && <div role="alert" className="warning">{error}</div>}
      <footer><button type="button" onClick={close}>{firstRun ? "稍后设置，使用本地数据" : "取消"}</button><button type="submit" className="primary" disabled={saving}>{saving ? "保存中…" : "保存设置"}</button></footer>
    </form>
  </Modal>;
}
