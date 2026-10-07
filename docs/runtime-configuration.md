# 运行时配置

源码和安装包共用同一套中性默认值，不包含特定用户的远端或本地绝对路径。第一次打开应用，在“工作空间设置”填写 SSH 别名、远端 Python、实验根目录；数据目录可按项目需要填写。未配置时仍可离线查看已有历史、图和列表；启动训练需要有效的远端环境。

## 配置文件位置

- macOS：`~/Library/Application Support/AI Experiment/config.local.json`。
- Windows：`%LOCALAPPDATA%\AI Experiment\config.local.json`。
- Linux：`$XDG_DATA_HOME/ai-exp-app/config.local.json`，未设置时为 `~/.local/share/ai-exp-app/config.local.json`。
- 既有源码工作空间：保留仓库根目录 `config.local.json` 和 `.local/`，不会自动迁移。
- 自定义数据目录：`<APP_DATA_DIR>/config.local.json`。
- 指定其他配置文件：设置 `AI_EXP_CONFIG_FILE`。

`config.local.json` 已加入 `.gitignore`，不进入安装包。应用设置原子保存此文件；它只包含路径和连接别名，不保存 SSH 密码。安装或覆盖更新应用保留数据目录中的配置。

## 示例

将下面占位符替换成自己的路径；这些占位符不能直接用来启动实验。

```json
{
  "ssh_alias": "gpu",
  "connection_mode": "ssh",
  "remote_agent": "<REMOTE_APP_ROOT>/agent.pyz",
  "remote_root": "<REMOTE_APP_ROOT>",
  "remote_state_dir": "<REMOTE_APP_ROOT>/state",
  "remote_python": "<REMOTE_PYTHON>",
  "remote_gpu_probe": "",
  "remote_runs_root": "<REMOTE_RUNS_ROOT>",
  "remote_data_root": "",
  "remote_projects_root": "<REMOTE_PROJECTS_ROOT>",
  "remote_groups_root": "<REMOTE_RUNS_ROOT>/.gpu_exp_groups",
  "remote_import_root": "<REMOTE_RUNS_ROOT>/",
  "local_import_root": "<LOCAL_HISTORY_ROOT>/"
}
```

中性默认值是 `ssh_alias=gpu`、远端 Python `python3`、远端安装根目录 `.local/share/ai-exp-app`、远端浏览 `/`、本地历史浏览 `~/gpu_downloads/`。实验根目录初始为空，必须填写。数据目录可留空，由项目参数或命令自行管理。`remote_state_dir` 和 `remote_groups_root` 留空时分别由安装根目录和实验根目录派生。

`connection_mode` 默认为 `ssh`。仅当网页后台就在 GPU 主机上运行时使用 `local`，通过 `remote_python` 子进程执行既有 `remote_agent`，不进行 SSH 自连接。此模式的 Python、代理与 `remote_state_dir` 都必须为绝对路径；状态目录必须复用既有代理目录。`ssh_alias` 在本机模式中是唯一主机标识，不支持其他主机的项目。配置与缓存属于后台主机，手机上的“本地目录”指 GPU 目录。详见 [手机接入](mobile-web.md)。

本地缓存与数据目录保持既有独立布局：安装版缓存位于应用数据目录的 `gpu_downloads`，本地历史浏览起点用于导入其他目录，不改变已导入缓存位置。

## 远端安装

本地配置完成后运行 `ai-experiment install-agent`（源码版使用虚拟环境内同名命令）。安装器使用配置中的 SSH 别名与远端根目录，把中性 agent 和独立的 `config.local.json` 安装到远端。远端配置文件位于 `<REMOTE_APP_ROOT>/config.local.json`，不会藏在 zipapp 里面。远端状态目录沿用配置值，升级不会迁移实验或重建调度状态。

## 本地环境变量

| 变量 | 用途 |
| --- | --- |
| `AI_EXP_DATA_DIR` | 工作空间数据库和服务状态目录 |
| `AI_EXP_CONFIG_FILE` | 显式选择本地配置文件 |
| `AI_EXP_CACHE_ROOT` | 实验文件缓存根目录 |
| `AI_EXP_WEB_ROOT` | 构建后的前端目录 |
| `AI_EXP_PORT` | localhost 服务端口，默认 `8765` |

新工作空间默认使用系统应用数据目录。已存在系统应用配置或数据库时复用它；否则保留既有源码 `.local/` 工作空间；两者都不存在才使用新的系统默认目录。桌面、CLI 和网页共用同一规则。开发或测试应显式指定独立工作空间，避免与日常数据混用。

Mac／Linux 示例：`export AI_EXP_DATA_DIR="$PWD/.local"` 和 `export AI_EXP_CONFIG_FILE="$PWD/config.local.json"`。Windows PowerShell 使用 `$env:AI_EXP_DATA_DIR="$PWD/.local"` 和 `$env:AI_EXP_CONFIG_FILE="$PWD/config.local.json"`。变量只影响当前终端及其启动的进程。

运行中的实验持有提交时的代码、Python、数据和产物目录；修改应用设置用于后续操作，不会修改正在执行的训练配置。项目自己的配置可覆盖全局 Python、数据与实验根目录。

设计和内部验收记录不包含在公开仓库中。公开说明使用占位符；用户设置只保存在自己的 config.local.json。

`remote_gpu_probe` 可留空以使用 NVIDIA 默认查询。其他设备／提供商可填写远端 Python 设备查询脚本的绝对路径，返回唯一整数 index 与布尔 available 的 JSON 数组。接入 Agent 应核实真实设备命名空间、占用和可分配资源；失败不会自动视为全部空闲。详见 [云端环境接入](../skills/experiment-workbench-setup/references/cloud-environments.md)。

## 跨设备同步（开发版）

本节适用于 `main`，尚未包含在 `v0.5.0` 安装包。

先将 GPU 网页后台与桌面后台更新到支持同步的版本。在 GPU 网页顶栏“跨设备同步”中选择“云端共享工作空间”；Mac 选择“与云端同步”，指定 GPU 网页的 loopback 端口。Mac 经配置中的 SSH 别名、Python 与既有连接复用访问该端口，不需另建公网服务。配置保存为 `workspace_sync_mode`（`off` / `hub` / `client`）和 `workspace_sync_port`（默认 `8765`）。默认关闭，避免自行合并已有工作空间。每个同步中心对应工作空间配置中的主机；其他 SSH 主机的项目与历史保留本端，避免不同 GPU 的同名目录被错误合并。

同步项目与代码选择、命名参数组、上次运行参数、参数显示备注、云端来源历史的名称／备注／标签／归档、表格模板及图表设置。不同后台的本地 ID 自动映射，原缓存目录保持；初次同名但参数不同的参数组保留两份。每次更换到启用的同步模式前，后台在自身 `backups/workspace-sync-*` 中保存 SQLite 与配置副本。

后台约每 10 秒交换一次元数据，可手动“立即同步”。断网时本地编辑和缓存仍可用，恢复后重试。同一项两端同时修改或首次内容不一致时，显示冲突，由用户选择本机或云端版本；删除索引使用墓碑，避免重连后自动恢复。删除历史索引不会通过同步删除源文件。

SSH／认证、本机路径、通知权限、主题和当前图表勾选仍为设备本地设置。原始 args／metrics／log／checkpoint 不通过此元数据通路传输，仍由历史管理更新本端缓存。从本地目录导入的历史保留在当前后台，并在同步窗口显示数量；需要跨设备使用的已有 GPU 实验请从云端目录导入。首次收到另一端的云端历史时，会建立本机缓存索引，后台随后获取文件；已有曲线不会因改备注重复下载。
