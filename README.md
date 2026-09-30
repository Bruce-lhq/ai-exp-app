# AI Experiment · 实验工作台

通过 SSH 管理 GPU 实验，在本地查看日志、曲线和对比表。提供独立 macOS 应用与 localhost 网页入口；关闭工作台不影响远端训练和队列。

当前为早期版本，训练启动、参数读取和严格续跑首先适配 **launcher 风格的 PyTorch 项目**，尚不是任意 GitHub 项目开箱即用的训练器。图表与表格可使用本地缓存离线生成。

## 功能

- 选择远端代码目录、Git 分支或版本，提交时固定代码快照。
- 命名参数组、JSON 导入／导出、参数备注、分类、排序及 K/M/B 数值输入。
- GPU 分配、可拖动队列、运行日志、实时曲线、接管外部 torchrun 进程及确认暂停／停止。
- 手动导入本地或远端历史，刷新缓存、重命名、归档和导出；受管实验退出后补同步。
- 多实验曲线、PPL 对数坐标、图例及配色编辑、PNG 导出。
- 表格模板、baseline 差值、指标 min/max/final 及采样位置、Markdown 导出／复制。
- 原始超参数和指标只读；缺失参数可补填，备注可编辑，补充内容独立保存，不改写原始 args。
- 历史管理中的统一严格续跑入口：载入 checkpoint 到编辑区后，再启动或加入队列。

## 安装与启动

### macOS 应用

公开安装包通过本仓库的 **Releases** 分发，DMG 不存放在 Git 仓库。首次 Release 发布前，可按下文从源码构建。

1. 下载与机器架构匹配的 `AI-Experiment-macOS.dmg`，打开后将 `AI Experiment.app` 拖入“应用程序”。
2. 打开应用，按首次设置填写 SSH 别名和目录；也可选择“稍后设置”先导入本地历史。
3. 把应用保留在程序坞。再次点击会聚焦已有窗口。

原生应用使用 macOS WebKit，包含 Python 服务和前端，无须另装 Python／Node 或打开浏览器。远端代理目前仍需用源码中的安装脚本部署，见 Quickstart。构建目标为 macOS 13+，按构建机器架构生成；当前实测 Apple Silicon，Intel 尚未验收。现有构建使用 ad-hoc 签名，尚未完成 Developer ID 签名与公证，系统可能阻止首次打开。版本更新保留本地数据。

### 从源码使用 localhost 版本

本地要求 Python 3.12+、[uv](https://docs.astral.sh/uv/getting-started/installation/)、Node.js 22 和 npm；当前验收环境为 macOS。Linux 可使用网页入口，但尚未完成完整平台验收；Windows 原生入口暂不支持。

将 `YOUR_ACCOUNT` 替换成仓库拥有者，并确保已配置 GitHub SSH：

```bash
git clone git@github.com:YOUR_ACCOUNT/ai-exp-app.git
cd ai-exp-app
uv venv --python 3.12
uv pip sync requirements.lock
uv pip install --no-deps -e .
npm --prefix web ci
npm --prefix web run build
```

每次在源码目录启动：

```bash
export AI_EXP_DATA_DIR="$PWD/.local"
export AI_EXP_CONFIG_FILE="$PWD/config.local.json"
.venv/bin/python -m ai_exp_app.desktop
```

然后打开 <http://127.0.0.1:8765>。服务仅监听本机地址；终端 `Ctrl+C` 退出本地服务，远端训练继续。开发前端时可另开终端运行 `npm --prefix web run dev`，但正常使用以构建后的 8765 页面为准。

### 从源码构建 Mac 应用

先完成上述依赖安装，并安装 Xcode Command Line Tools，再运行：

```bash
uv pip install pyinstaller
.venv/bin/python scripts/build_macos.py
```

产物位于 `dist/AI Experiment.app` 和 `dist/AI-Experiment-macOS.dmg`。发布时附到 GitHub Release，不提交到仓库；流程见 [发布说明](docs/releasing.md)。

## Quickstart：首次接入实验

### 1. 准备 SSH 与训练环境

工作台复用系统 SSH 配置和认证，不收集密码。先保证终端可以连接自己的 GPU 主机，例如 `~/.ssh/config`：

```sshconfig
Host gpu
    HostName gpu.example.com
    User your-user
    IdentityFile ~/.ssh/id_ed25519
    ControlMaster auto
    ControlPersist 10m
    ControlPath ~/.ssh/ai-exp-%C
```

```bash
ssh gpu 'python3 --version; nvidia-smi'
```

远端需 Python 3.8+、可用 NVIDIA GPU 和 `nvidia-smi`。训练使用的 Python 环境需包含 PyTorch 和项目依赖，代码和数据须事先放在远端。工作台不自动上传代码或准备数据。

### 2. 填写工作空间设置并安装远端代理

打开工作台的“工作空间设置”，填写自己的路径；以下只是示例：

| 设置 | 示例 |
| --- | --- |
| SSH 主机别名 | `gpu` |
| 云端工作台目录 | `/your_exp/workbench` |
| 云端代码目录 | `/your_exp/projects/` |
| 云端实验目录 | `/your_exp/runs/` |
| 云端数据目录 | `/your_exp/data/` |
| 云端 Python（高级设置） | `/your_exp/venv/bin/python` |
| 本地实验导入目录 | `~/gpu_downloads/` |

配置保存为本机 `config.local.json`，不进入版本控制。保存后，在源码仓库运行安装脚本：

```bash
# localhost 版本，与上面的启动命令使用同一配置文件
AI_EXP_DATA_DIR="$PWD/.local" AI_EXP_CONFIG_FILE="$PWD/config.local.json" \
  .venv/bin/python scripts/install_remote.py

# Mac 应用版本，读取应用内保存的配置
AI_EXP_CONFIG_FILE="$HOME/Library/Application Support/AI Experiment/config.local.json" \
  .venv/bin/python scripts/install_remote.py
```

二选一。安装器通过 SSH 部署标准库 zipapp 和独立远端配置，原子更新代理，不重建实验状态。代理部署的 `python3` 与训练 Python 可以不同。详细配置、文件位置和环境变量见 [运行时配置](docs/runtime-configuration.md)。

### 3. 先导入已有实验查看数据

在“历史管理”选择本地或云端导入，选中含实验文件的目录。支持 `args.json`、`metrics.jsonl` 和日志文件；缺失文件或指标会提示，不会补零。导入后可重命名，再到“画图与列表”勾选实验，切换指标或表格，下载 PNG／Markdown。

绘图与列表直接读本地缓存，不要求在线。远端文件变化后，在历史管理点击“同步最终文件”更新缓存；运行中的实验也可导入并刷新。移除历史条目不删除源目录，之后可重新导入。

### 4. 接入代码并启动一个小实验

在“配置实验”添加常用项目，通过云端目录选择器选中代码目录，再选择工作树／Git 分支或版本。工作台读取源码默认参数，允许命名保存参数组；先确认参数、训练环境和 GPU 数，再启动或加入队列。“运行监控”查看状态、日志和曲线。

当前适配要求目录包含 `train.py`，提供 `build_parser()`，使用兼容的 argparse 参数、`--run-dir`／`--data-root` 入口，以及支持的训练产物格式。解析器读取与训练状态判断仍含 launcher 专用规则，其他项目需要适配；不能仅凭存在 `train.py` 判定完全兼容。

### 5. 暂停与严格续跑

运行监控中暂停／停止需要确认；外部实验须先接管进程。暂停使用已有 checkpoint，当前不会要求训练程序先保存新 checkpoint。

续跑从“历史管理”选择云端实验，点击“载入续跑到编辑区”，核对项目、checkpoint 和配置后启动。只支持完整训练状态恢复；checkpoint、代码／数据或 GPU 数不符合约束时拒绝续跑。结果写入新的实验目录，来源实验保留。本地历史不能直接作为云端续跑来源。

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
           代码快照 / GPU 调度 / 状态与日志
                       |
                  PyTorch torchrun
```

| 目录 | 职责 |
| --- | --- |
| `web/` | React 页面、Chart.js 绘图、参数及表格编辑 |
| `src/ai_exp_app/` | 本地 API、SQLite 索引、SSH 传输、历史同步、指标统计 |
| `remote/ai_exp_remote/` | 远端代理、调度与进程管理、快照、训练适配、严格续跑校验 |
| `macos/AIExperiment/` | 独立窗口、单实例入口、系统通知与本地服务管理 |
| `scripts/` | 远端代理安装、Mac 构建与工作空间迁移 |
| `tests/`、`web/tests/` | 后端、前端单元与浏览器回归测试 |

远端保存训练文件和队列状态；本地保存项目、参数组、历史索引、图表／表格偏好及实验缓存。SSH 断线后保留缓存，重连补同步。提交实验时固定代码快照和参数，后续编辑不改变已提交任务。

本地 API 使用会话、同源检查和原生应用令牌保护，仅供本机使用。工作台会运行所选代码并反序列化 PyTorch checkpoint，项目与 checkpoint 应来自可信来源；SSH 主机的权限就是远端操作权限。它不是多人公网服务，也不提供不可信代码沙箱。

## 开发与测试

```bash
.venv/bin/python -m pytest -q
npm --prefix web test
npm --prefix web run build
cd web
npx playwright install chromium
npm run test:e2e
```

现成回归使用临时目录和模拟远端接口，不需要连接 GPU 或配置 SSH。GitHub Actions 执行 pytest、前端构建、Vitest 与 Chromium Playwright；测试失败时保留浏览器测试产物。

## Roadmap

- 将训练入口、产物格式和 checkpoint 校验拆成可扩展项目适配器。
- 首次向导自动检查 SSH 并安装远端代理。
- Developer ID 签名与公证、Intel Mac 与 Linux 验收；Windows 支持。
- 按项目能力支持暂停前保存 checkpoint，并展示最近恢复点及可能损失的进度。
- 多 seed／参数扫描、分组统计及工作空间配置备份。
- 可选本地代码同步；当前仅选择远端已有代码。

## License

[MIT](LICENSE)。第三方依赖保留各自许可证。
