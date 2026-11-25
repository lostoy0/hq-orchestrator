# HQ 运行数据格式（metrics schema）— 格式版本 v1

主会话把每个子任务和每次运行的数据记录成 JSONL：一行一个 JSON 对象，文件路径 `.hq/runs/<run_id>.jsonl`。
用 `skills/hq/scripts/metrics.py` 汇总成指标报告，`/hq-retro` 复盘时只读报告、不读原始记录。

## 通用规则

- 编码 UTF-8，一行一个对象，行内不能换行。
- `type` 取 `"task"` 或 `"run"`。其他 type、未知字段，读取方一律忽略。
- 所有字段都可能缺失或为 `null`，读取方必须容错；写入方拿不到值时写 `null`（不要编造）。
- 损坏的行（不是合法 JSON，或不是对象）由读取方跳过并计数。
- 一个 run 对应一个文件：多条 `task` 记录 + 一条 `run` 记录。`task` 通过 `run_id` 关联所属 run。
- 一个任务只记一条 `task`（重试、升档都累加在同一条里）。同一 `run_id`+`task_id` 出现多次时（比如同一次运行既在 `.hq/runs/` 又在 `~/.claude/hq/runs/`），读取方只算一条，后读到的覆盖先读到的。
- 格式版本：**v1**。run 记录里的 `plugin_version` 是插件版本，不是格式版本。不兼容改动必须升版本号。

## task 记录

“填写者”都是主会话（总指挥）；子会话的交付报告是数据来源。

| 字段 | 类型 / 取值 | 含义 | 何时填写 |
|---|---|---|---|
| type | `"task"` | 记录类型 | 创建时 |
| run_id | 字符串 | 所属 run | 创建时 |
| task_id | 字符串 | 任务 id（如 `t2`） | 规划完成时 |
| title | 字符串 | 任务标题 | 规划完成时 |
| project | 字符串 | 项目名 | 规划完成时 |
| kind | `code`/`docs`/`research`/`review`/`config` | 任务类型 | 规划完成时 |
| risk | `low`/`med`/`high` | 风险等级 | 规划完成时 |
| tier_score | 整数 0–10 | 难度评估总分 | 难度评估时 |
| tier | `T0`–`T4` | 最终使用的档位 | 难度评估时；升降档后更新为最终值 |
| host | `claude-code`/`codex`/`dsh`/`opencode`/`cursor`/`gemini`/`other`（可选） | 主会话所在宿主 | 派发时 |
| model | 字符串 | 最终使用的模型；跨厂商（非宿主自带模型）写成 `<cli>:<模型名>`，如 `codex:<模型名>` | 派发时（升降档后更新） |
| effort | 字符串 | 思考深度（low/medium/high/xhigh…） | 派发时（升降档后更新） |
| channel | `A`/`B`/`C`/`D`/`W`/`main` | 派发通道。`W` 是 CLI 子进程 worker（`cli-worker.sh`）；`main` 表示主会话自己做（含降级模式） | 派发时 |
| est_min | 数字 | 预计用时（分钟） | 派发前 |
| actual_min | 数字 | 实际用时（分钟） | 审核归并后 |
| tokens | 整数或 null | 消耗 token，口径见下方“用量口径” | 子会话交付后，拿不到写 null |
| cost_usd | 数字或 null | 花费（美元），**主要成本指标** | 同上 |
| attempts | 整数 | 尝试次数（首次为 1） | 每次重试时累加 |
| tier_changes | `[{from,to,reason}]` | 档位变更历史，无变更为 `[]` | 每次升降档时追加 |
| handoffs | 整数 | 中途交接给其他会话/模型的次数 | 发生交接时累加 |
| derived_tasks | 整数 | 由本任务派生出的新任务数 | 审核时 |
| checkpoints | 整数 | 子会话发出 CHECKPOINT 的次数 | 收到时累加 |
| user_manual_adjust | 布尔 | 用户是否手动调整过模型/档位/计划 | 发生时 |
| scope_violation | 布尔 | 是否改了范围之外的文件 | 审核时 |
| drift | 布尔 | 是否偏离任务目标 | 审核时 |
| drift_note | 字符串 | 偏离说明 | 审核时 |
| verify_level | `doc`/`code`/`high`/`e2e` | 说明里规定的验证级别（见 `SKILL.md` 第 8 步分级表） | 派发时 |
| verify_evidence | 字符串 | 验证证据（命令输出摘要等），空表示没做验证或没给证据 | 审核时 |
| verify_pass | 布尔 | 验证是否通过 | 审核时 |
| issues | `{review,integration,user,severity_max}` | 问题数：审核发现 / 合并时发现 / 用户反馈（整数）；`severity_max` 取 `none`/`minor`/`major` | 审核、合并、用户反馈时更新 |
| review_outcome | `pass`/`pass_with_fixes`/`rework`/`failed` | 审核结论 | 审核时 |
| user_corrections | 整数 | 用户纠正次数 | 发生时累加 |
| notes | 字符串 | 备注。没有专门字段的问题原因写在这里，便于复盘检索（如 `worktree 未忽略`、`删远程分支失败`） | 任意 |

示例：

```json
{"type":"task","run_id":"20260101-a","task_id":"t2","title":"metrics.py","project":"hq-orchestrator","kind":"code","risk":"low","tier_score":4,"tier":"T2","model":"sonnet","effort":"medium","channel":"B","est_min":15,"actual_min":22,"tokens":180000,"cost_usd":0.85,"attempts":1,"tier_changes":[],"handoffs":0,"derived_tasks":0,"checkpoints":0,"user_manual_adjust":false,"scope_violation":false,"drift":false,"drift_note":"","verify_level":"code","verify_evidence":"unittest 12 passed","verify_pass":true,"issues":{"review":1,"integration":0,"user":0,"severity_max":"minor"},"review_outcome":"pass_with_fixes","user_corrections":0,"notes":""}
```

## run 记录

由主会话填写：开始时填 `run_id`/`project`/`goal`/`started_at`/`plugin_version`，收尾时填其余字段。

| 字段 | 类型 / 取值 | 含义 |
|---|---|---|
| type | `"run"` | 记录类型 |
| run_id | 字符串 | run id，与文件名一致 |
| project | 字符串 | 项目名 |
| host | `claude-code`/`codex`/`dsh`/`opencode`/`cursor`/`gemini`/`other`（可选） | 主会话所在宿主 |
| goal | 字符串 | 用户目标 |
| started_at / ended_at | ISO8601 字符串 | 开始 / 结束时间 |
| wall_min | 数字 | 总耗时（墙钟分钟） |
| critical_path_min | 数字 | 关键路径预计用时（分钟） |
| tasks | 整数 | 任务总数 |
| max_concurrency | 整数 | 实际达到的最大并发 |
| throttle_events | 整数 | 因资源不足降并发/排队的次数 |
| autonomy_stops | 整数 | 因需要用户决定而停下的次数 |
| decisions | 整数 | 主会话自行做出的重要决定数 |
| integration_pass | 布尔 | 最终合并验证是否通过 |
| plugin_version | 字符串 | hq 插件版本 |
| standing_seq | 整数（可选） | 常驻模式下本会话的第几批；非常驻不写 |

示例：

```json
{"type":"run","run_id":"20260101-a","project":"hq-orchestrator","goal":"增加指标汇总","started_at":"2026-01-01T10:00:00Z","ended_at":"2026-01-01T11:00:00Z","wall_min":60,"critical_path_min":40,"tasks":5,"max_concurrency":3,"throttle_events":1,"autonomy_stops":1,"decisions":2,"integration_pass":true,"host":"claude-code","plugin_version":"0.3.0"}
```

## 用量口径

- **`cost_usd` 是主要成本指标**：它已经按各类 token 的不同单价折算，跨模型、跨通道可比。比较开销、写验收指标时优先用它。
- **`tokens` = input + output + cache_write（创建缓存）**，**不含 cache_read（读取缓存）**。缓存读取单价很低、数量却很大，算进去会让 tokens 虚高，看不出真实工作量。
  - 以下 A、B 是 Claude Code 宿主的取法（详见 `hosts/claude-code.md`）。
  - B 通道：从 `get_session` 的 `usage` 里按上式相加；拿不到分项就写 null。
  - W 通道：`cli-worker.sh usage --id <id>` 输出的 JSON，按同一口径取值。
  - 其他宿主：按宿主文档的 worker_usage 一行取值。
  - A 通道：返回结果里的 `subagent_tokens` 只是总数、分不出缓存读取时，`tokens` 写 null，把原始总数记进 `notes`（如 `subagent_tokens=73000`），避免两种口径混在一起。
- 主会话自己的消耗不计入任何 task 记录。

## 汇总口径（metrics.py）

`metrics.py` 只读取和汇总，不写入、不校验字段；记录由主会话直接追加。写完可以运行一次 `metrics.py .hq/runs` 确认能读、`损坏行数` 为 0。

缺失/null 的布尔按“否”、计数按 0 处理，分母为全部任务；均值、中位数、比值只统计有有效数值的记录；分母为 0 时显示 `-`。

报告各节与字段的对应：
- 质量门槛：漂移率（`drift` 或 `scope_violation`）、验证到位率（有 `verify_evidence` 且 `verify_pass`）、各环节问题/任务（`issues`）、major 数、返工率（`review_outcome` 为 rework/failed）、合并通过率（run 的 `integration_pass`）。
- 按档位、按模型/深度：一次通过率（`attempts`=1 且审核通过）、升档率（`tier_changes` 非空）、交接率、平均 cost_usd 和 tokens、actual/est 中位数。
- 效率（每个 run）：wall/关键路径、并行加速比（各任务 actual_min 之和 / wall_min）、max_concurrency、throttle_events。
- 总览的“缺记录任务数”：run 的 `tasks` 减去实际有记录的任务数（不为负）。
- 调档与检查点：升档任务数、其中 `checkpoints`>0 的比例（近似“升档由检查点触发、而不是等失败”）、checkpoints / handoffs / derived_tasks 合计、`user_manual_adjust` 次数。
