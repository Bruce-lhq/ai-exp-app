# 手动接入云端实验

使用 Agent 的用户可由它完成以下步骤。手动操作前，先按 [README](../README.md#安装与启动) 安装并启动本地应用。

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

Windows OpenSSH 配置只保留 Host、HostName、User、IdentityFile 和需要的 Port；上面的 ControlMaster／ControlPersist／ControlPath 仅用于支持连接复用的 Mac／Linux 客户端。

确认主机指纹后测试：

```bash
ssh gpu 'python3 --version; nvidia-smi'
```

远端代理需 Linux（含 `/proc`）和 Python 3.8+。GPU 调度默认使用 `nvidia-smi`；其他设备或提供商分配规则可由 Agent 配置 `remote_gpu_probe`，见 [云端环境接入](../skills/experiment-workbench-setup/references/cloud-environments.md)。训练自身使用项目指定的环境，不要求 PyTorch。代码与数据需放在远端，如何上传及安装项目依赖见接入 SKILL。

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

桌面安装包中的 CLI 和独立 CLI 均包含远端代理。保存工作空间设置后，使用同一工作空间的 CLI 安装：

```bash
ai-experiment install-agent --read-only
ai-experiment install-agent
```

`--read-only` 也会连接并部署代理，但使远端代理拒绝启动／停止等写操作，适合先检查接入；检查后重新执行不带该选项的安装命令启用完整功能。源码版用 `.venv/bin/ai-experiment`（Windows 用 `.venv/Scripts/ai-experiment.exe`）。显式选择了环境变量工作空间时，安装代理也使用相同的变量。

安装器原子更新标准库 zipapp，不重建队列或训练状态。详细字段见 [运行时配置](runtime-configuration.md)。

### 3. 声明训练项目

在云端代码目录放置 `workbench.project.json`。完整格式和可运行小示例见 [项目接入协议](project-integration.md)。启动命令使用 argv 数组，每个参数独立一项；不通过 shell 展开。普通脚本、多进程启动器、其他可执行程序均可声明。

在“配置实验”添加该云端代码目录，选择工作树或 Git 版本。工作台读取该版本的项目声明，显示默认参数，提交时冻结代码和配置。先以小模型或小步数验证参数、输出和 GPU 使用，再运行正式任务。

### 4. 导入已有实验

“历史管理”导入包含 `args.json`、`metrics.jsonl`、`train.log` 的本地或云端目录；文件可缺失，会提示，不会补零。`metrics.jsonl` 支持任意有限数值指标及 `step`、`tokens_seen`、`elapsed_s` 横轴；不会要求特定模型指标。其他格式先按接入 SKILL 转换到新的标准目录，保留原始文件。

到“画图与列表”勾选历史、选择指标与可用横轴，下载 PNG／Markdown。远端文件变化后在历史管理点击“同步最终文件”；绘图不自动访问云端。

### 5. 暂停与严格续跑

暂停／停止需确认，使用进程身份检查；不会要求训练程序主动保存新 checkpoint。外部进程接管目前只支持可识别的 torchrun 进程与可选的终端分组工具；普通项目应由工作台启动才能可靠控制。

接入 Agent 先检查项目已有的保存／恢复代码；若已支持严格续跑，就复用现有校验或生成与项目格式匹配的验证器，配置后可在历史管理点击“载入续跑到编辑区”。验证器应校验模型、优化器、调度器、随机数、数据游标，以及代码／数据／参数／GPU 数兼容性；仅保存权重不够。结果写入新的实验目录，来源保留。尚未配置校验器时会提示需要检查并完成接入，这不代表项目不支持；Agent 应继续核实，而不是直接关闭此功能。本地历史不能直接作为云端续跑来源。

