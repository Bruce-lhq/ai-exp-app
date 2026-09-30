# 项目接入协议（版本 1）

工作台负责快照、GPU 队列、进程和缓存。训练项目负责实际训练与指标输出。项目文件 `workbench.project.json` 与代码一起进入所选版本的快照，不存放 SSH 凭据。

## 最小配置

完整可执行示例位于 [examples/minimal](../examples/minimal/)。它使用普通 Python 脚本与 CPU 运算，不依赖训练框架，不要求 `train.py`，输出任意 `loss`、`accuracy` 指标。通过工作台提交仍占用其 GPU 队列分配的卡；要先在本地直接验证输出，可运行：

```bash
python3 examples/minimal/experiment.py --output /tmp/workbench-example-run --steps 8 --rate 0.1
```

请使用不存在的新输出目录。

```json
{
  "version": 1,
  "command": ["{python}", "experiment.py", "--output", "{run_dir}"],
  "parameters": [
    {"name": "steps", "type": "integer", "default": 8, "flag": "--steps"},
    {"name": "learning_rate", "type": "number", "default": 0.1, "flag": "--rate"}
  ],
  "environment": {"PYTHONUNBUFFERED": "1"}
}
```

`command` 为非空 argv 数组，逐项执行，不通过 shell。不要把整条命令写成一个字符串，也不要依靠 `~`、`$HOME`、管道等 shell 展开；需要的路径应先确定为绝对路径。工作目录为代码快照。普通命令、模块入口或项目自己的多卡启动器均可使用：

```json
{"command": ["{python}", "-m", "torch.distributed.run", "--standalone", "--nproc-per-node={gpu_count}", "trainer.py", "--output", "{run_dir}"]}
```

上例只是可选启动器，工作台本身不依赖它。多卡训练项目必须声明正确的多进程命令；仅分配多张卡不会自动增加进程。

## 参数与占位符

| 字段 | 含义 |
| --- | --- |
| `parameters` | 显式参数数组；推荐使用，不导入训练模块 |
| `name` | 参数原始名称，JSON 与编辑区使用 |
| `type` | `integer`、`number`、`boolean`、`string` 或 `number_or_choice`（数字／字符串选项混合） |
| `default` | 源码实际默认值；缺省表示没有默认值 |
| `flag` | 实际 CLI 选项，例如 `--rate` |
| `choices` | 可选的允许值数组 |
| `action` | `store`（默认）、`store_true` 或 `store_false` |
| `help`、`group` | 可选显示说明与参数分组 |
| `constraints` | 可选数字约束，例如 `{"min": 1, "max": 100}` |
| `controlled_parameters` | 由命令固定提供的字段，不出现在可编辑参数中 |
| `runtime.workers_parameter` | 可选：明确声明哪个整数参数控制 GPU 数量；缺省不将数据加载 workers 当作卡数 |
| `environment` | 传给训练进程的字符串环境变量对象，不应包含私密令牌 |

命令与环境变量值支持 `{python}`（项目／全局训练 Python）、`{project_dir}`（快照）、`{run_dir}`（新实验目录）、`{gpu_count}`、`{gpu_ids}`、`{parameter_file}`。分配的卡默认通过 `CUDA_VISIBLE_DEVICES` 指定；其他设备运行时由 Agent 设置其真实可见性变量，设备清单可通过运行时 `remote_gpu_probe` 扩展，见 [云端环境接入](../skills/experiment-workbench-setup/references/cloud-environments.md)。源码中的物理编号不能代替进程内的逻辑 GPU 编号。

工作台把编辑区参数追加为 CLI 选项。`null` 不传，布尔开关按 `action` 处理。名称与实际选项无需一致。没有参数也可以声明 `"parameters": []`。

JSON 配置项目使用 `"parameter_style": "json"`，并在命令里放 `{parameter_file}`，例如 `["{python}", "fit.py", "--config", "{parameter_file}", "--output", "{run_dir}"]`；该文件保存提交的参数对象，CLI 参数不追加。当前参数编辑支持标量，不支持任意嵌套配置编辑；复杂配置可由项目包装脚本合并。协议中的 training/runtime 是分组名；原项目若使用这些同名字段，可用明确的编辑区别名和实际 flag／原生字段映射。指标横轴字段也应与普通指标区分，必要时保留来源名并使用 metrics/ 前缀别名。

可选 argparse 发现：不提供 `parameters` 时，以 `entrypoint`（默认 `train.py`）和 `parser_function`（默认 `build_parser`）探测解析器。只适用于独立、可抽取的解析器；若解析器依赖框架导入、动态配置或辅助函数，应显式声明参数。不要通过执行训练入口获得参数。

## 标准输出文件

实验目录为 `{run_dir}`。训练程序应自行建立它；工作台避免提前建立目录，兼容要求新目录的程序。

- `args.json`：训练程序可保存实际参数；未生成时，工作台保存提交参数。已有文件不覆盖。
- `metrics.jsonl`：每行一个 JSON 对象，每次采样后及时 flush。
- `train.log`：项目可自行写入。工作台实时采集 stdout/stderr 到尝试日志，退出后保留 `launch.log`；若没有 `train.log`，将尝试日志复制为它。
- `run.json`：工作台运行身份、阶段与退出状态。

指标例子：

```json
{"step": 1, "elapsed_s": 0.5, "metrics": {"loss": 2.4, "accuracy": 0.3}}
{"step": 2, "tokens_seen": 1000000, "elapsed_s": 1.0, "metrics": {"loss": 1.8, "accuracy": 0.5}}
```

数值字段可位于顶层或 `metrics` 对象内。横轴使用 `step`、`tokens_seen` 或 `elapsed_s`；不要伪造训练 token 数以满足图表。缺失指标只跳过该实验对应曲线；非有限值和损坏行会警告。退出码 0 表示任务完成，不要求特定的结束日志文字。

已有 CSV／其他 JSONL 可用 [接入 SKILL](../skills/experiment-workbench-setup/SKILL.md) 的转换脚本生成新的标准目录。转换应保留原始文件并记录字段映射。当前不直接解析任意 TensorBoard、W&B 或二进制指标存储。

## 严格续跑

由接入 Agent 检查项目已有的 checkpoint 保存、加载和训练循环，判断其能否完整恢复。已有严格续跑实现应复用其校验，或由 Agent 根据真实格式编写验证器。尚未声明 `resume` 仅表示接入未完成，不代表项目不支持；工作台暂不启动未经校验的续跑，也不自动反序列化未知文件。Agent 配置项目验证器后即可启用：

```json
{
  "resume": {
    "checkpoint": "latest.pt",
    "flag": "--resume",
    "validator": ["{python}", "verify_checkpoint.py", "--checkpoint", "{checkpoint}", "--request", "{request}"]
  }
}
```

`checkpoint` 是实验目录内的相对文件路径。`flag` 只在续跑时追加；也可提供 `resume.command`，其 argv 包含 `{resume}`，用于与普通启动完全不同的续跑命令。普通 command 不能含未设置的 `{resume}`。

验证器在可信项目目录运行，不访问 GPU。它读取 `{request}` JSON：`phase` 为 `preview` 或 `validate`。提交校验还包含新任务的 `training`、`runtime.gpu_count`、`snapshot` 和 `checkpoint_path`。必须检查代码／数据／配置兼容性及完整状态，并将唯一的 JSON 写到 stdout（其他日志写 stderr），成功退出：

```json
{
  "strict": true,
  "compatible": true,
  "verified_state": {"model": true, "optimizer": true, "scheduler": true, "rng": true, "data_position": true},
  "training": {"steps": 1000, "learning_rate": 0.001},
  "runtime": {"gpu_count": 1},
  "tokens_seen": 1000000,
  "errors": []
}
```

这些布尔值是验证器检查结果，不能无条件填写 `true`。不使用某项状态的训练也应明确验证其缺省行为能精确恢复。可通过 `required_state` 增加 scaler 或 tokenizer 等检查。工作台还核对原训练参数与 GPU 数量，检查复制前后 checkpoint 身份，并为新任务固定其副本；验证器本身负责格式、内容与代码／数据身份的可靠性。仅保存权重、猜测缺失状态、允许学习率或卡数变化，都不能声明为严格续跑。

外部已有实验的严格续跑同样依赖项目验证器；不要求由工作台生成原 checkpoint。接入工具不会替训练程序补造缺失状态。

## 代码目录与排除规则

快照不按 data、runs 或 checkpoints 这样的通用目录名推断它们是产物；这些目录可能包含真正的代码。Agent 应检查实际结构，在项目 API 的 config.exclusions 中声明需要排除的相对路径模式，例如 ["artifacts", "artifacts/**"]。工作树与 Git 版本都会应用同样的排除规则；数据、环境和大型产物通常放在代码目录外。不要排除共享源码或配置目录。
