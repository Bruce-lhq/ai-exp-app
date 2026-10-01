# CLI 使用说明

CLI、桌面和网页使用同一份工作空间、API 与本地缓存。命令需要服务时会启动或复用自己的 localhost 后台；不要求打开浏览器或桌面窗口。默认路径和隔离方式见 [运行时配置](runtime-configuration.md)。

## 安装与启动

从 Release 下载对应系统／架构的 CLI 压缩包，完整解压。不要只复制可执行文件，旁边的 `_internal` 是运行时依赖。在该目录执行 `./ai-experiment --help`；Windows PowerShell 使用 `.\ai-experiment.exe --help`。下文假设可执行文件已加入 PATH；源码安装使用虚拟环境内同名命令。

```bash
ai-experiment service start
ai-experiment service status --json
ai-experiment config show --json
ai-experiment doctor
```

第一次接入可打开 `service start` 返回的网页设置，也可将自己填写的工作空间设置保存为 JSON 后执行：

```bash
ai-experiment config set --file settings.json
ai-experiment install-agent --read-only
ai-experiment install-agent
ai-experiment doctor --remote
```

只有 `--remote` 或实际远端操作访问 SSH；普通 `doctor`、缓存出图和表格不连接云端。首次完整接入仍建议让 Agent 按 [SKILL](../skills/experiment-workbench-setup/SKILL.md) 检查训练代码与项目声明。

## 导入与离线导出

```bash
ai-experiment history import --source local --path /path/to/run --name "Example run" --json
ai-experiment history list --json
ai-experiment plot HISTORY_ID --metric accuracy --axis step --output comparison.png
ai-experiment table HISTORY_ID --output comparison.md
ai-experiment history export HISTORY_ID --output experiment.zip
```

用真实历史 ID 替换 `HISTORY_ID`，多个 ID 用空格分开。选 token 横轴时 `--axis tokens`，图中按 B 显示；PPL 默认对数纵轴。缺失指标会警告，并跳过该实验，其他指标仍可用。没有任何可画样本时返回错误。PNG 和 Markdown 都从缓存生成；远端数据更新使用 `history sync HISTORY_ID`，本地源更新使用相同命令。

已有输出文件默认不覆盖；明确覆盖时加 `--force`。表格不指定 `--output` 时打印 Markdown，便于复制或重定向。

`--request-file` 可给 `plot` 或 `table` 传完整 API JSON，包含坐标范围、图例顺序／名字／配色或表格列、baseline 和格式。参数格式分别对应 `/api/analysis/series` 与 `/api/analysis/table`。PNG 使用同一缓存解析和样式原则，由服务端 Matplotlib 渲染；与浏览器 Chart.js 在字体和排版上可能有细微差异。

图的请求文件示例：

```json
{
  "metric": "accuracy",
  "x_axis": "step",
  "title": "Validation accuracy",
  "settings": {"yScale": "linear", "width": 1536, "height": 1044},
  "appearance": {
    "HISTORY_ID": {"name": "Baseline", "color": "#4c78a8", "order": 0}
  }
}
```

CLI 用命令行历史 ID 设置比较对象，传入请求文件中的 `history_ids` 不会覆盖该选择。

## 项目、运行与队列

```bash
ai-experiment project list --json
ai-experiment run list --json
ai-experiment queue list --json
ai-experiment history list --json
```

各级 `--help` 列出参数和必填项，例如 `ai-experiment run start --help`。启动与队列需要项目 ID 和参数 JSON；严格续跑走项目验证后的历史续跑入口，同样使用远端验证凭据，不能通过 CLI 绕过。已有数据的超参数和指标只读，允许补填缺失字段。

暂停／停止、永久删除等需要确认；自动脚本必须明确给 `--yes`。非交互输入不会默认确认。命令参数以 argv 传递，不展开 shell；不要把密码、私钥或 token 写入请求文件。

## 退出与脚本集成

```bash
ai-experiment service stop --yes
```

它停止自己的本地后台，打开的网页／窗口会暂时失去服务；远端实验和队列继续。重复启动会复用现有工作空间服务；其他工作空间占据相同端口时会报错，避免连接错数据。可使用 `AI_EXP_PORT` 为独立工作空间指定其他端口。

`--json` 提供机器可读结果；PNG／ZIP 导出仍写指定文件。退出码：`0` 成功，`2` 输入错误，`3` 连接／服务错误，`4` API 错误，`5` 缺少确认或取消。高级 `api` 子命令只接受 localhost 地址，沿用会话和同源校验。
