# iPhone 浏览器与 GPU 常驻工作台

这个入口让网页、后台和缓存运行在 GPU 主机。Mac 可以关机；手机只需要能够独立访问 GPU 的 VPN 和 SSH 隧道。它复用同一实验代理、状态和队列，不在手机或 GPU 上另建训练调度器。桌面版仍默认通过 SSH 使用。

已在 Ubuntu 20.04 x86_64 GPU 主机上使用独立 Python 3.13 环境部署，并验证历史曲线、表格、PNG 下载、隔离小实验和后台自动重启。手机尺寸的 WebKit 测试已通过，iPhone 主屏幕 Web App 真机验收也已完成。

## 1. 准备后台

完整网页后台需要独立的 Python 3.12+ 环境；代理仍使用现有训练 Python（3.8+）。不要升级或修改训练环境。Ubuntu 24.04 桌面二进制不能代替 Ubuntu 20.04 的源码部署。

在源码电脑准备部署包，整个过程不连接 SSH：

```bash
npm --prefix web ci
npm --prefix web run build
.venv/bin/python scripts/build_gpu_web.py
```

生成 `dist/releases/AI-Experiment-GPU-Web.tar.gz`，包含 Python 源码、前端和锁定依赖，不包含任何配置、数据库、实验、缓存或认证信息。它没有内置 Python；需在 GPU 用专用环境安装。上传及解压到专用目录之后，在 GPU 上执行（uv 需已安装；Python3.12若不存在需单独准备）：

```bash
cd /your_exp/mobile-workbench/ai-experiment-web
uv venv --python 3.12
uv pip sync --python .venv/bin/python requirements.lock
uv pip install --python .venv/bin/python --no-deps -e .
mkdir -p workspace
```

所有路径均为占位符，需要替换。GPU 无网络时由接入 Agent 准备匹配 Ubuntu/Python/CPU 架构的运行时和依赖 wheel；不能上传 Mac 虚拟环境直接使用。

## 2. 复用现有代理

将下面内容保存为 GPU 部署目录的 `workspace/config.local.json`，权限设为 `600`，不进入 Git。`remote_agent`、`remote_python`、`remote_state_dir` 必须填绝对路径。**remote_state_dir 必须是既有代理状态目录**；留空或创建新状态目录会失去现有队列，本机模式会拒绝留空。

```json
{
  "connection_mode": "local",
  "ssh_alias": "gpu",
  "remote_root": "/your_exp/workbench",
  "remote_agent": "/your_exp/workbench/agent.pyz",
  "remote_python": "/your_exp/training-env/bin/python",
  "remote_state_dir": "/your_exp/workbench/state",
  "remote_runs_root": "/your_exp/runs",
  "remote_projects_root": "/your_exp/projects",
  "remote_import_root": "/your_exp/runs/",
  "remote_groups_root": "/your_exp/runs/.gpu_exp_groups",
  "local_import_root": "/your_exp/runs/"
}
```

本机模式仍使用 `ssh_alias` 作为代理主机标识，但不会进行 SSH 自连接。所有项目必须使用该标识；其他主机标识会拒绝，以免把不同主机的实验误操作成本机任务。数据目录按实际项目补充，或由项目自身配置管理。保留现有代理的部署配置与只读标志；不要为手机接入重新初始化代理或覆盖正在使用的代理版本。

在 GPU 部署目录启动（确认 8765 未被其他服务占用；不要盲目停止占用者）：

```bash
export AI_EXP_DATA_DIR="$PWD/workspace"
export AI_EXP_CONFIG_FILE="$PWD/workspace/config.local.json"
export AI_EXP_CACHE_ROOT="$PWD/workspace/gpu_downloads"
export AI_EXP_WEB_ROOT="$PWD/web/dist"
export AI_EXP_PORT=8765
.venv/bin/ai-experiment service start
.venv/bin/ai-experiment doctor
```

服务仅监听 `127.0.0.1`。`service start` 脱离启动终端，但不提供崩溃自动重启；正式常驻部署应由 systemd 或平台现有 supervisor 管理。支持 systemd 的主机可使用下面单元，替换目录并设置合适的服务用户，随后由接入 Agent 校验加载。容器中 PID1 不是 systemd 时使用提供商 supervisor 或 tmux 中的受控重启脚本，不假定 systemd 可用。

```ini
[Unit]
Description=AI Experiment GPU Web
After=network.target

[Service]
Type=simple
WorkingDirectory=/your_exp/mobile-workbench/ai-experiment-web
Environment=AI_EXP_DATA_DIR=/your_exp/mobile-workbench/ai-experiment-web/workspace
Environment=AI_EXP_CONFIG_FILE=/your_exp/mobile-workbench/ai-experiment-web/workspace/config.local.json
Environment=AI_EXP_CACHE_ROOT=/your_exp/mobile-workbench/ai-experiment-web/workspace/gpu_downloads
Environment=AI_EXP_WEB_ROOT=/your_exp/mobile-workbench/ai-experiment-web/web/dist
Environment=AI_EXP_PORT=8765
ExecStart=/your_exp/mobile-workbench/ai-experiment-web/.venv/bin/ai-experiment service run
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

先用 `service start` 验收后，需先 `service stop --yes` 再交给 supervisor 管理同一工作空间，避免重复实例。停止网页后台不会停止代理队列或训练。

## 3. iPhone 入口

手机 VPN 能访问 GPU 后，在 Termius 创建 Local Port Forwarding：

| 字段 | 值 |
| --- | --- |
| Local Port | `8765` |
| Bind Address | `127.0.0.1` |
| Intermediate Host | 你的 GPU SSH 主机、端口和用户 |
| Destination Address | `127.0.0.1` |
| Destination Port | `8765` |

启动隧道后在 Safari 打开 `http://127.0.0.1:8765`。SSH 认证由 Termius 管理，工作台不保存 SSH 密码，不需要 Mac 钥匙串。SSH 隧道加密传输网页/API；不开放 GPU 公网 HTTP 端口。

### 添加到 iPhone 主屏幕

首次在 Safari 打开上述入口，点“分享”→“添加到主屏幕”，名称保留 **AI Experiment**。如果系统提供“作为网页 App 打开”选项，请保持开启。之后开启 VPN 和 Termius 隧道，直接点击主屏幕的 AI Experiment 图标即可；工作台以独立窗口打开。

网页包含 standalone manifest、192/512 图标、180像素 Apple touch icon 和状态栏颜色；无需 Xcode 或 Apple 开发者签名。添加后名称或图标未更新时，可移除旧主屏幕入口，再从刷新后的页面重新添加。这一版不缓存服务/API，也不提供断网操控；下载与分享使用 iOS WebKit 的系统行为。

手机页面提供四区导航、触摸按钮和队列上下移，表格横向滚动，曲线在手机上单独显示可换行图例。桌面显示与 PNG 导出保留原图样式。暂停/停止仍需确认，严格续跑仍需项目真实校验。后台断线时保留已显示状态、给出恢复提示；恢复隧道后自动重连，刷新页面重新取得登录会话。

关闭隧道或 iOS 回收 Termius 会影响访问，不会停止 GPU 实验。隧道的后台存活时间取决于 iOS 与 SSH 客户端的运行状态；此版不保证系统推送、离线操控或无需隧道的公网访问。

如果页面只在重新启动端口转发后短暂可用，应检查 SSH 客户端切到后台后的运行状态。SSH Keep Alive 是连接心跳间隔，不能代替 iOS 后台运行支持。验收需包括切换到 Safari／主屏幕 Web App 后持续访问数分钟，不能只确认首次打开成功。页面启动时会显示加载提示；脚本加载中断或长时间未完成时提供重新加载入口。它不能自动重启手机上的 SSH 转发。

## 4. 数据位置与人工验收

手机界面的“本地目录”指后台所在 GPU 的目录，不是 iPhone 文件夹。手机可下载网页导出的 PNG/Markdown/实验归档。GPU 工作台配置、历史备注、模板和缓存独立于 Mac；Mac 与手机共同操作的是代理的同一队列与实验，元数据不会自动双向同步。通过历史管理刷新各自缓存。手机缓存位于 GPU，源实验缺失时已有曲线仍可读缓存；手机离线时无法访问 GPU 网页。

正式启用前应确认：回环绑定；SSH退出后后台存活；Mac关机仍能访问；已有队列状态一致；只读日志/历史/曲线/表格；隔离极小任务的启动、停止、严格续跑和排队；手机窄屏参数编辑、下载、断线重连。不得使用现有正式训练验证暂停/停止/删除。
