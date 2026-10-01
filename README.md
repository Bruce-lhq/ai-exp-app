# AI Experiment · 实验工作台

[![CI](https://github.com/Bruce-lhq/ai-exp-app/actions/workflows/ci.yml/badge.svg)](https://github.com/Bruce-lhq/ai-exp-app/actions/workflows/ci.yml)

通过 SSH 管理训练任务，在本地查看日志、曲线和对比表。提供独立 macOS 应用与 localhost 网页入口；关闭工作台不影响远端任务和队列。绘图与列表读取本地缓存，可离线使用。

## 最简单的开始方法

打开 Claude Code、Codex 或其他能操作终端的 AI Agent，把下面整段话复制给它：

```text
请克隆 https://github.com/Bruce-lhq/ai-exp-app.git，读取并加载 skills/experiment-workbench-setup/SKILL.md，按其指引帮我完成 AI Experiment 的安装与接入。
```

你只需要提供 Agent 询问的连接信息和代码位置；密码、私钥不用发到聊天里。没有现成实验时，可在确认后运行一个极小的验收任务。使用哪家云 GPU、目录怎么组织、训练用什么框架，都由 Agent 根据实际项目检查并接入；它需要能够访问对应代码和云端环境。

项目接入不限定训练框架、脚本名称或模型。Agent 根据实际代码生成 `workbench.project.json`，必要时适配配置与指标输出，并检查项目已有的严格续跑能力。

<details>
<summary>可选：把接入 SKILL 安装到 Agent 工具中</summary>

直接读取 [接入 SKILL](skills/experiment-workbench-setup/SKILL.md) 即可使用，无须安装。要作为命名 skill 使用，复制整个目录到工具的 skill 目录；保留 `references/` 和 `scripts/`，不要只复制 SKILL.md。

Claude Code 可使用项目目录 `.claude/skills/experiment-workbench-setup/`（[官方说明](https://code.claude.com/docs/en/skills)）；Codex 使用其当前版本支持的 skill 目录（[官方说明](https://developers.openai.com/codex/skills/)）。

</details>

## 功能

- 选择远端代码目录、Git 分支或版本，提交时固定代码快照。
- 命名参数组、JSON 导入／导出、参数备注、分类、排序及 K/M/B 数值输入。
- GPU 分配、可拖动队列、运行日志、实时曲线及确认暂停／停止。
- 手动导入本地或远端历史，刷新缓存、重命名、归档和导出；受管实验退出后补同步。
- 任意数值指标对比、PPL 对数坐标、图例及配色编辑、PNG 导出。
- 表格模板、baseline 差值、指标 min/max/final 及采样位置、Markdown 导出／复制。
- 原始超参数和指标只读；缺失参数可补填，备注可编辑，补充内容独立保存。
- 接入 Agent 验证项目现有完整状态续跑后，可从历史管理载入续跑到参数编辑区。

## 安装与启动

### macOS 应用

从 [GitHub Releases](https://github.com/Bruce-lhq/ai-exp-app/releases) 下载 `AI-Experiment-macOS.dmg`，将应用拖入“应用程序”，打开并按首次设置配置工作空间。可先选择“稍后设置”导入本地历史。将应用保留在程序坞，再次点击会聚焦已有窗口。

应用包含 Python 服务和前端，使用系统 WebKit，无须另装 Python／Node 或打开浏览器。当前公开包目标为 Apple Silicon、macOS 13+；Intel 尚未验收。使用 ad-hoc 签名，尚未完成 Developer ID 公证；首次打开可能需按 [Apple 的说明](https://support.apple.com/102445) 在系统设置中允许。更新应用保留本地数据。远端代理通过源码安装脚本部署。

### 从源码使用 localhost

本地要求 Python 3.12+、[uv](https://docs.astral.sh/uv/getting-started/installation/)、Node.js 22 和 npm。macOS 已验收；Linux 可使用网页入口，完整平台验收尚未完成；Windows 原生入口暂未支持。

```bash
git clone https://github.com/Bruce-lhq/ai-exp-app.git
cd ai-exp-app
uv venv --python 3.12
uv pip sync requirements.lock
uv pip install --no-deps -e .
npm --prefix web ci
npm --prefix web run build
```

每次从源码目录启动：

```bash
export AI_EXP_DATA_DIR="$PWD/.local"
export AI_EXP_CONFIG_FILE="$PWD/config.local.json"
.venv/bin/python -m ai_exp_app.desktop
```

打开 <http://127.0.0.1:8765>。服务只监听本机；终端退出本地服务后，远端任务继续。前端开发可另开终端运行 `npm --prefix web run dev`。

## 手动接入云端实验

使用 Agent 的用户可由它完成以下步骤。手动操作前，先按上文安装并启动本地应用。

### 1. 确认 SSH

工作台使用系统 SSH 配置和认证，不收集密码。先确认终端能连接 GPU 主机。示例 `~/.ssh/config`：

```sshconfig
Host gpu
    HostName gpu.example.com
    User your-user
    IdentityFile ~/.ssh/id_ed25519
    ControlMaster auto
    ControlPersist 10m
    ControlPath ~/.ssh/ai-exp-%C
```

确认主机指纹后测试：

```bash
ssh gpu 'python3 --version; nvidia-smi'
```

远端代理需 Linux（含 `/proc`）和 Python 3.8+。GPU 调度默认使用 `nvidia-smi`；其他设备或提供商分配规则可由 Agent 配置 `remote_gpu_probe`，见 [云端环境接入](skills/experiment-workbench-setup/references/cloud-environments.md)。训练自身使用项目指定的环境，不要求 PyTorch。代码与数据需放在远端，如何上传及安装项目依赖见接入 SKILL。

### 2. 设置工作空间并安装代理

在应用“工作空间设置”填自己的路径：

| 设置 | 示例 |
| --- | --- |
| SSH 别名 | `gpu` |
| 云端工作台目录 | `/your_exp/workbench` |
| 云端代码目录 | `/your_exp/projects/` |
| 云端实验目录 | `/your_exp/runs/` |
| 云端 Python | `/your_exp/venv/bin/python` |
| 云端数据目录 | 可留空；由项目命令或参数指定 |
| 本地实验导入目录 | `~/gpu_downloads/` |

远端代理安装器位于源码仓库中。即使使用 Mac 应用，手动部署也需要先取得匹配版本源码，并完成上文“从源码使用 localhost”中的 Python 依赖安装（无需构建前端）；以下命令均在源码根目录执行。

源码版使用启动时的同一份 `config.local.json`（已被 Git 忽略）：

```bash
AI_EXP_DATA_DIR="$PWD/.local" AI_EXP_CONFIG_FILE="$PWD/config.local.json" \
  .venv/bin/python scripts/install_remote.py
```

Mac 应用版改用应用保存的配置：

```bash
AI_EXP_CONFIG_FILE="$HOME/Library/Application Support/AI Experiment/config.local.json" \
  .venv/bin/python scripts/install_remote.py
```

安装器原子更新标准库 zipapp，不重建队列或训练状态。详细字段见 [运行时配置](docs/runtime-configuration.md)。

### 3. 声明训练项目

在云端代码目录放置 `workbench.project.json`。完整格式和可运行小示例见 [项目接入协议](docs/project-integration.md)。启动命令使用 argv 数组，每个参数独立一项；不通过 shell 展开。普通脚本、多进程启动器、其他可执行程序均可声明。

在“配置实验”添加该云端代码目录，选择工作树或 Git 版本。工作台读取该版本的项目声明，显示默认参数，提交时冻结代码和配置。先以小模型或小步数验证参数、输出和 GPU 使用，再运行正式任务。

### 4. 导入已有实验

“历史管理”导入包含 `args.json`、`metrics.jsonl`、`train.log` 的本地或云端目录；文件可缺失，会提示，不会补零。`metrics.jsonl` 支持任意有限数值指标及 `step`、`tokens_seen`、`elapsed_s` 横轴；不会要求特定模型指标。其他格式先按接入 SKILL 转换到新的标准目录，保留原始文件。

到“画图与列表”勾选历史、选择指标与可用横轴，下载 PNG／Markdown。远端文件变化后在历史管理点击“同步最终文件”；绘图不自动访问云端。

### 5. 暂停与严格续跑

暂停／停止需确认，使用进程身份检查；不会要求训练程序主动保存新 checkpoint。外部进程接管目前只支持可识别的 torchrun 进程与可选的终端分组工具；普通项目应由工作台启动才能可靠控制。

接入 Agent 先检查项目已有的保存／恢复代码；若已支持严格续跑，就复用现有校验或生成与项目格式匹配的验证器，配置后可在历史管理点击“载入续跑到编辑区”。验证器应校验模型、优化器、调度器、随机数、数据游标，以及代码／数据／参数／GPU 数兼容性；仅保存权重不够。结果写入新的实验目录，来源保留。尚未配置校验器时会提示需要检查并完成接入，这不代表项目不支持；Agent 应继续核实，而不是直接关闭此功能。本地历史不能直接作为云端续跑来源。

## 架构

```text
macOS AppKit + WKWebView          浏览器 localhost
             \                    /
              React + Chart.js 前端
                       |
              本地 FastAPI 服务
              SQLite + 文件缓存
                       |
                   系统 SSH
                       |
               远端 Python zipapp
            代码快照 / GPU 队列 / 进程管理
                       |
          项目声明的训练命令与输出协议
```

| 目录 | 职责 |
| --- | --- |
| `web/` | React 页面、Chart.js、参数与表格编辑 |
| `src/ai_exp_app/` | API、SQLite、SSH、历史同步、指标统计 |
| `remote/ai_exp_remote/` | 远端代理、调度、进程管理、快照、项目声明与续跑验证 |
| `macos/AIExperiment/` | 独立窗口、单实例入口、通知和本地服务管理 |
| `skills/experiment-workbench-setup/` | Agent 接入流程、检查脚本与参考资料 |
| `examples/` | 无训练框架依赖的最小接入示例 |
| `scripts/` | 远端安装、Mac 构建与工作空间迁移 |
| `tests/`、`web/tests/` | 后端、前端与浏览器回归 |

远端保存训练文件与队列；本地保存项目、参数组、历史索引、图表／表格偏好和缓存。断线保留缓存，重连补同步。提交时固定代码与参数，后续编辑不改变已提交任务。

本地 API 仅供本机使用，具备会话、同源与原生应用令牌检查。项目命令和可选 checkpoint 验证器是用户选择的可执行代码；只接入可信项目。工作台不提供不可信代码沙箱或多人公网服务。

## 开发与测试

### 运行测试

```bash
.venv/bin/python -m pytest -q
npm --prefix web test
npm --prefix web run build
cd web
npx playwright install chromium
npm run test:e2e
```

CI 使用临时目录、模拟远端接口和小型普通命令测试，不需要连接真实 GPU 或配置 SSH。GitHub Actions 执行 pytest、构建、Vitest 和 Chromium Playwright。

### 从源码构建 Mac 应用

完成“从源码使用 localhost”中的依赖安装，并安装 Xcode Command Line Tools 后，在源码根目录执行：

```bash
uv pip install pyinstaller==6.22.3
.venv/bin/python scripts/build_macos.py
```

产物为 `dist/AI Experiment.app`、`dist/AI-Experiment-macOS.dmg`，通过 Release 分发，不进 Git。公开构建的中性 Python 环境与检查方法见 [发布说明](docs/releasing.md)。

## Future work

- 应用内自动检查 SSH、上传代码与安装代理；当前通过接入 SKILL 完成。
- TensorBoard／其他指标存储的原生接入；当前使用标准 JSONL 或转换脚本。
- 更广泛的外部进程接管和其他 GPU／调度系统支持。
- Developer ID 签名与公证、Intel Mac、Linux 全面验收与 Windows 支持。
- 按项目能力在暂停前保存 checkpoint，展示恢复点与可能损失的进度。
- 多 seed／参数扫描、分组统计与工作空间备份。

## License

[MIT](LICENSE)。第三方依赖保留各自许可证；Mac 包包含项目许可证与第三方许可证清单。
