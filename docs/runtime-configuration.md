# 运行时配置

源码和安装包共用同一套中性默认值，不包含特定用户的远端或本地绝对路径。第一次打开应用，在“工作空间设置”填写 SSH 别名、远端 Python、实验根目录和数据目录。未配置时仍可离线查看已有历史、图和列表；启动训练需要有效的远端环境。

## 配置文件位置

- 开发版：仓库根目录 `config.local.json`。
- Mac 安装版：`~/Library/Application Support/AI Experiment/config.local.json`。
- 自定义数据目录：`<APP_DATA_DIR>/config.local.json`。
- 指定其他配置文件：设置 `AI_EXP_CONFIG_FILE`。

`config.local.json` 已加入 `.gitignore`，不进入安装包。应用设置原子保存此文件；它只包含路径和连接别名，不保存 SSH 密码。安装或覆盖更新应用保留数据目录中的配置。

## 示例

将下面占位符替换成自己的路径；这些占位符不能直接用来启动实验。

```json
{
  "ssh_alias": "gpu",
  "remote_agent": "<REMOTE_APP_ROOT>/agent.pyz",
  "remote_root": "<REMOTE_APP_ROOT>",
  "remote_state_dir": "<REMOTE_APP_ROOT>/state",
  "remote_python": "<REMOTE_PYTHON>",
  "remote_runs_root": "<REMOTE_RUNS_ROOT>",
  "remote_data_root": "<REMOTE_DATA_ROOT>",
  "remote_projects_root": "<REMOTE_PROJECTS_ROOT>",
  "remote_groups_root": "<REMOTE_RUNS_ROOT>/.gpu_exp_groups",
  "remote_import_root": "<REMOTE_RUNS_ROOT>/",
  "local_import_root": "<LOCAL_HISTORY_ROOT>/"
}
```

中性默认值是 `ssh_alias=gpu`、远端 Python `python3`、远端安装根目录 `.local/share/ai-exp-app`、远端浏览 `/`、本地历史浏览 `~/gpu_downloads/`。实验根目录和数据目录初始为空，不能凭猜测启动训练。`remote_state_dir` 和 `remote_groups_root` 留空时分别由安装根目录和实验根目录派生。

本地缓存与数据目录保持既有独立布局：安装版缓存位于应用数据目录的 `gpu_downloads`，本地历史浏览起点用于导入其他目录，不改变已导入缓存位置。

## 远端安装

本地配置完成后运行 `scripts/install_remote.py`。安装器使用配置中的 SSH 别名与远端根目录，把中性 agent 和独立的 `config.local.json` 安装到远端。远端配置文件位于 `<REMOTE_APP_ROOT>/config.local.json`，不会藏在 zipapp 里面。远端状态目录沿用配置值，升级不会迁移实验或重建调度状态。

## 本地环境变量

| 变量 | 用途 |
| --- | --- |
| `AI_EXP_DATA_DIR` | 工作空间数据库和服务状态目录 |
| `AI_EXP_CONFIG_FILE` | 显式选择本地配置文件 |
| `AI_EXP_CACHE_ROOT` | 实验文件缓存根目录 |
| `AI_EXP_WEB_ROOT` | 构建后的前端目录 |
| `AI_EXP_PORT` | localhost 服务端口，默认 `8765` |

源码版按 README 显式指定工作空间与配置文件，避免与已安装 Mac 应用的数据混用。未指定数据目录时，若本机存在 Mac 应用数据库则复用该工作空间，否则使用源码的 `.local/`。

运行中的实验持有提交时的代码、Python、数据和产物目录；修改应用设置用于后续操作，不会修改正在执行的训练配置。项目自己的配置可覆盖全局 Python、数据与实验根目录。

设计和内部验收记录不包含在公开仓库中。公开说明使用占位符；用户设置只保存在自己的 config.local.json。
