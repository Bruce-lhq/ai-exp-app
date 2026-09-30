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
const requiredFields = new Set(["ssh_alias", "remote_agent", "remote_python", "remote_runs_root", "remote_data_root"]);

export function LocalSettingsDialog({ initial, firstRun, close, notify }: {
  initial: LocalSettings;
  firstRun: boolean;
  close: () => void;
  notify: (message: string) => void;
}) {
  const [draft, setDraft] = useState(initial), [saving, setSaving] = useState(false), [error, setError] = useState("");
  const input = ([key, title]: readonly [string, string]) => (
    <label key={key} className="local-setting-field">
      {title}{requiredFields.has(key) && " *"}
      <input aria-label={title} value={draft[key] || ""} onChange={(event) => setDraft({ ...draft, [key]: event.target.value })} />
    </label>
  );
  return <Modal title={firstRun ? "设置工作空间" : "工作空间设置"} close={close}>
    <p>填写这台电脑使用的 SSH 主机和目录。设置仅保存在本机；稍后设置也可以查看本地历史、画图和列表。</p>
    <p>* 为运行云端实验所需；云端实验目录和数据目录请填写绝对路径。</p>
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
      <div className="local-settings-fields">{fields.map(input)}</div>
      <details className="local-settings-advanced"><summary>高级设置</summary><div className="local-settings-fields">{advancedFields.map(input)}</div></details>
      {error && <div role="alert" className="warning">{error}</div>}
      <footer><button type="button" onClick={close}>{firstRun ? "稍后设置，使用本地数据" : "取消"}</button><button type="submit" className="primary" disabled={saving}>{saving ? "保存中…" : "保存设置"}</button></footer>
    </form>
  </Modal>;
}
