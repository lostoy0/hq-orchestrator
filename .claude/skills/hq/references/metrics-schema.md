# HQ 运行数据格式（metrics schema）— 格式版本 v1

主会话把每个子任务和每次运行的数据记录成 JSONL：一行一个 JSON 对象，文件路径 `.hq/runs/<run_id>.jsonl`。
用 `skills/hq/scripts/metrics.py` 汇总成指标报告，`/hq-retro` 复盘时只读报告、不读原始记录。

## 通用规则

- 编码 UTF-8，一行一个对象，行内不能换行。
- `type` 取 `"task"`、`"run"` 或 `"merge"`（v0.11.0 起，合入组）。其他 type（包括旧版本写过的 `"monitor"`）、未知字段，读取方一律忽略。
- 所有字段都可能缺失或为 `null`，读取方必须容错；写入方拿不到值时写 `null`（不要编造）。
- 损坏的行（不是合法 JSON，或不是对象）由读取方跳过并计数。
- 一个 run 对应一个文件：多条 `task` 记录 + 一条 `run` 记录。`task` 通过 `run_id` 关联所属 run。
- 一个任务只记一条 `task`（重试、升档都累加在同一条里）。同一 `run_id`+`task_id` 出现多次时（比如同一次运行既在 `.hq/runs/` 又在 `~/.claude/hq/runs/`），读取方只算一条，后读到的覆盖先读到的。
- `merge` 记录同样去重：同一 `run_id`+`batch_id`+`group_seq`（`batch_id` 可省略）只算一条，后读到的覆盖先读到的；没有 `group_seq` 的 merge 记录，内容完全相同的只算一条。没有 `task_id` 的 task 记录不去重。
- 格式版本：**v1**。run 记录里的 `plugin_version`/`plugin_version_at_start` 是插件版本，不是格式版本。不兼容改动必须升版本号；只新增可选字段、放宽取值的改动（如 v0.3.3 的 `found_issues`、`followups`、`verify_pass: "partial"`）仍是 v1。

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
| plan_tier | `T0`–`T4`（可选，v0.6.0 起） | 按计划清单执行时，清单里预估的档位（`/hq-plan` 打分）；不是按计划执行的任务省略 | 规划完成时 |
| host | `claude-code`/`codex`/`dsh`/`opencode`/`cursor`/`gemini`/`other`（可选） | 主会话所在宿主 | 派发时 |
| model | 字符串 | 最终使用的模型；跨厂商（非宿主自带模型）写成 `<cli>:<模型名>`，如 `codex:<模型名>` | 派发时（升降档后更新） |
| effort | 字符串 | 思考深度（low/medium/high/xhigh…） | 派发时（升降档后更新） |
| channel | `A`/`B`/`C`/`D`/`W`/`main` | 派发通道。`W` 是 CLI 子进程 worker（`cli-worker.sh`）；`main` 表示主会话自己做（含降级模式） | 派发时 |
| est_min | 数字 | 预计用时（分钟） | 派发前 |
| actual_min | 数字 | 实际用时（分钟）：从派发到 worker 交付的墙钟时间，**不含**等待审核、合并的时间；重试时累加各次尝试的用时。取法见 `runtimes.md` 的 worker_usage | 审核归并后 |
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
| verify_pass | 布尔或 `"partial"` | 验证是否通过。只做了部分验证（如只核对了文档、没实机运行）写 `"partial"`，并在 `verify_evidence` 写明缺了哪一步；不要为了好看写 `true` | 审核时 |
| issues | `{review,integration,user,severity_max}` | 问题数：审核发现 / 合并时发现 / 用户反馈（整数）；`severity_max` 取 `none`/`minor`/`major` | 审核、合并、用户反馈时更新 |
| found_issues | `[{severity, origin_task_id}]`（可选，v0.3.3 起） | 审核类任务（独立审核、合并后审核）**自己发现的**问题，每个问题一项：`severity` 取 `minor`/`major`，`origin_task_id` 是引入问题的任务的 `task_id`（同一 run）。汇总时计入来源任务的 integration 问题数，不计入审核任务自己；审核任务不要再把同一批问题重复写进来源任务的 `issues.integration` | 审核任务交付后 |
| followups | `[{desc, fixed_in}]`（可选，v0.3.3 起） | 本任务留下的待修项（审核时“先合并、之后再修”的小问题）：`desc` 一句话描述；`fixed_in` 是修复它的版本号或 `run_id/task_id`，还没修写 `null`。修好后回填 `fixed_in`（可以只改旧记录的这一个字段） | 审核时登记，修复时回填 |
| review_outcome | `pass`/`pass_with_fixes`/`rework`/`failed` | 审核结论 | 审核时 |
| user_corrections | 整数 | 用户纠正次数 | 发生时累加 |
| assist | 字符串或 null | 可选（v0.5.0 起）。由辅助执行者完成时写 profile 名（如 `kimi`、`codex`），主宿主自己做的写 null 或省略。辅助失败被主宿主接手时仍写原 profile，靠 `handoffs` 区分 | 任务结束时 |
| shard_group / task_type | 字符串（可选，v0.11.0 起） | 分片任务所属的分片组（同一批同一种工作单元，如 `patrol`）；任务类型（`patrol` 巡检、`dev` 开发、`docs`、`test`…） | 规划完成时 |
| units_planned / units_actual | 整数（可选） | 计划和实际完成的工作单元数 | 规划时 / 交付后 |
| unit_min_est / overhead_min | 数字（可选） | 预估的单元耗时、子会话固定开销（分钟） | 规划时 |
| resplit / resplit_from | 布尔 / 字符串（可选） | 本片是否被再拆；由哪片拆出来 | 再拆时 |
| test_scope / test_min | `related`/`full`、数字（可选） | 子会话的测试范围（关联 / 全量）和测试耗时 | 交付后 |
| rework_rounds | 整数（可选） | 返工轮数（修复后复测、同一问题反复出现、被退回） | 交付后 |
| flags | 字符串数组（可选，v0.11.0 起） | 规则标记，用于按规则分组复盘：`bias:+1(tier)`、`bias:+1(effort)`（规则 9 上调）、`downgrade:user_allowed(-N)`（规则 11 授权降档）、`rate_limited`、`assist_unavailable:<原因>`、`assist_auto_models`、`billing:<计费方>`、`effort_env:<值>`、`tier:not-applied`。旧数据写在 notes 里的同样识别（`bias:+1(cost_low)` 视为 `bias:+1(tier)`） | 发生时追加 |
| score | `{scope,ambiguity,context,risk,verify}`（可选，v0.12.0 起） | 难度评估 5 维打分（`calibration.md` “5 维打分”表），每项整数 0–2。用来检验哪一维打偏了；拿不到的维度写 null | 难度评估时 |
| independent_review | `{ran,trigger,findings,major}`（可选，v0.12.0 起） | 独立审核：`ran` 布尔（本任务是否实际做了独立审核；触发了但没做写 false）；`trigger` 取 `high`（high 级）/`tier`（T3 及以上）/`lines`（改动超过约 300 行）/`assist_lines`（辅助执行者产出超过约 150 行）/`other`；`findings` 审核发现的问题数，`major` 其中 major 数（整数）。没触发独立审核的任务省略整个字段 | 审核时 |
| review_wait_min | 数字（可选，v0.12.0 起） | 子会话交付到主会话开始审核的分钟数（不含在 `actual_min` 里）；用来判断巡检间隔是否偏长 | 开始审核时 |
| notes | 字符串 | 备注。没有专门字段的问题原因写在这里，便于复盘检索（如 `worktree 未忽略`、`删远程分支失败`） | 任意 |

示例：

```json
{"type":"task","run_id":"20260101-a","task_id":"t2","title":"metrics.py","project":"hq-orchestrator","kind":"code","risk":"low","tier_score":4,"tier":"T2","model":"sonnet","effort":"medium","channel":"B","est_min":15,"actual_min":22,"tokens":180000,"cost_usd":0.85,"attempts":1,"tier_changes":[],"handoffs":0,"derived_tasks":0,"checkpoints":0,"user_manual_adjust":false,"scope_violation":false,"drift":false,"drift_note":"","verify_level":"code","verify_evidence":"unittest 12 passed","verify_pass":true,"issues":{"review":1,"integration":0,"user":0,"severity_max":"minor"},"review_outcome":"pass_with_fixes","user_corrections":0,"followups":[{"desc":"补 Windows 路径用例","fixed_in":null}],"notes":""}
{"type":"task","run_id":"20260101-a","task_id":"t5","title":"独立审核 t2","kind":"review","risk":"low","tier":"T2","verify_level":"doc","verify_evidence":"只核对了文档和 diff，未实机运行","verify_pass":"partial","found_issues":[{"severity":"minor","origin_task_id":"t2"}],"review_outcome":"pass"}
```

## run 记录

由主会话填写：开始时填 `run_id`/`project`/`goal`/`started_at`/`plugin_version_at_start`，收尾时填其余字段（含 `plugin_version`）。

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
| plugin_version_at_start | 字符串（v0.3.3 起） | 运行开始时生效的 hq 插件版本（本次运行按哪个版本的规则执行）。开始时填 |
| plugin_version | 字符串 | 运行**产出**的 hq 插件版本：本次运行改了插件自身并升了版本时写新版本，否则与 `plugin_version_at_start` 相同。收尾时填。旧记录只有这一个字段，含义是运行时生效的版本 |
| standing_seq | 整数（可选） | 常驻模式下本会话的第几批；非常驻不写 |
| from_recommendation | 布尔（可选） | 常驻模式：本批是否来自上一批的推荐（用户回复“按推荐”或自动继续） |
| recommended_next | 整数（可选） | 常驻模式：本批结束时推荐了几条下一批任务；完工声明时为 0 |
| concurrency_limit / target_shard_min | 整数 / 数字（可选，v0.11.0 起） | 本次的并发上限、分片目标时长；用于并发利用率和片数建议 |
| reserved_slots / max_overhead_ratio | 整数 / 数字（可选） | 片数建议用：为再拆、公共文件修复等预留的并发槽数（没有时 0），子会话固定开销占一片时长的上限（没有时 0.3；可以是 0）。与 `scale.py shards` 的同名参数一致 |
| assist_disabled | `[{profile,reason}]`（可选，v0.5.1 起） | 本次被停用（熔断）的辅助执行者及原因（`unavailable:<原因>` / `consecutive_failures` / `max_failures` / `same_as_host`）；没有就省略 |
| stage / stage_mode / review_rounds / review_findings / open_assumptions（可选，v0.6.0 起） | 见 `stages/common.md` 第 8 节 | 阶段技能（如 `/hq-plan`）的运行：阶段名、模式、评审轮数、各级意见数、交给用户的待确认条数。`metrics.py` 目前不汇总 |

示例：

```json
{"type":"run","run_id":"20260101-a","project":"hq-orchestrator","goal":"增加指标汇总","started_at":"2026-01-01T10:00:00Z","ended_at":"2026-01-01T11:00:00Z","wall_min":60,"critical_path_min":40,"tasks":5,"max_concurrency":3,"throttle_events":1,"autonomy_stops":1,"decisions":2,"integration_pass":true,"host":"claude-code","plugin_version_at_start":"0.3.0","plugin_version":"0.3.0"}
```

## merge 记录（v0.11.0 起）

每次巡检合入一组已交付分片后写一条：

| 字段 | 类型 | 含义 |
|---|---|---|
| type / run_id | `"merge"` / 字符串 | |
| group_seq | 整数 | 本批第几组 |
| shards | 字符串数组 | 这一组合入的 task_id（推迟的不算） |
| verify_runs | 整数 | 这一组跑了几次校验（正常为 1；失败定位后复测会增加） |
| full_test / full_test_min | 布尔 / 数字 | 这次是否跑了全量测试、耗时 |
| reasons | 字符串数组 | 跑或没跑全量的原因（主会话按 `scale-out.md` 第 5 节的全量节点判断，自由文本，不导出） |
| pass / culprits / conflicts | 布尔 / 数组 / 数组 | 校验结果、定位到的分片、冲突文件 |
| wait_min | 数字 | 为攒批等待的分钟 |

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
- 质量门槛：漂移率（`drift` 或 `scope_violation`）、验证到位率（有 `verify_evidence` 且 `verify_pass` 为 `true`；`"partial"` 不算到位，单列“partial 数”，JSON `verify_partial`）、各环节问题/任务（`issues`；integration 另加审核任务 `found_issues` 归到来源任务的问题）、major 数（`severity_max` 为 major，或被归因了 major 问题）、返工率（`review_outcome` 为 rework/failed）、合并通过率（run 的 `integration_pass`）。
  - **审核归因**（v0.3.3）：按同一 run 内的 `task_id` 把审核任务的每个 `found_issues` 计到 `origin_task_id` 那个任务头上，不计入审核任务自己。“审核归因数”（JSON `attributed_issues`）是归到本范围任务的个数，“未归因数”（`unattributed_found_issues`）是 `origin_task_id` 缺失、不在本 run 或等于审核任务自己 `task_id` 的个数（不会归到审核任务自己）。若审核任务的 `found_issues` 和来源任务自己的 `issues.integration` 都记了同一问题会重复计数，按约定只记在审核任务里。归因同样用于 3f 的漏网问题/任务和 3g 的漏到合并/漏网 major（按来源任务的档位、版本、验证级别统计）。
  - “partial 数”列和归因两列只在数据里有 `"partial"` / `found_issues` 时才出现，旧数据的报告不变。
- 按档位、按模型/深度：一次通过率（`attempts`=1 且审核通过）、升档率（`tier_changes` 非空）、交接率、平均 cost_usd 和 tokens、actual/est 中位数。
  - **有值数**（v0.3.3）：3a/3b/3c/3d 分组表在 n 旁有“有值数 cost/tokens/ratio”列（JSON `cost_n`、`tokens_n`、`ratio_n`），是各均值、中位数实际用到的任务数；“5. 开销”表有“有值数 tokens/cost”（`tokens_n`、`cost_n`）。n 大而有值数小时均值不可靠，复盘引用均值时同时引用有值数。
  - **归一化用时比**（v0.3.3）：分组 JSON 另有 `low_n`、`low_first_pass_k`、`low_first_pass_rate`（只算 `risk`=low 的任务）和 `low_norm_ratio_median`、`low_norm_ratio_n`：每个任务的 actual/est 先除以所在 run 全部任务（所有档位，排除数据矛盾 run）actual/est 的中位数，再取该组 risk=low 任务的中位数。
  - **信号“可能降档”**（v0.3.3 起）：只看 `risk`=low 的任务。某组（档位或模型/深度）risk=low 且有用时数据的任务 ≥ 5 个（`low_norm_ratio_n`）、risk=low 任务一次通过率 100%（`low_first_pass_k` = `low_n`）、归一化中位数 < 0.7（比较时留 1e-9 容差，恰好 0.7 的浮点误差不触发）才触发，否则不触发。信号的 `n` 是 `low_n`，置信度按 `low_first_pass_k`/`low_n` 对 80%（`FULL_PASS_FLOOR`）计算。归一化消除“整次运行都估时偏保守”的影响，只看低风险任务是为了不对中高风险任务给出降档提示。旧规则（全组一次通过率 100% 且原始 actual/est 中位数 < 0.7）已废弃。
- 效率（每个 run）：wall/关键路径、并行加速比（各任务 actual_min 之和 / wall_min，即平均同时在跑几个任务）、加速比上限（actual_min 之和 / critical_path_min，任务图允许的最好情况）、max_concurrency、throttle_events。
  - **数据矛盾**：加速比 > max_concurrency × 1.1，或某个任务的 actual_min > wall_min，说明 actual_min 口径不对（常见原因是把等审核、合并的时间也算了进去）。备注列标“数据矛盾”，该 run 不产生加速比信号，改为提示核对口径；它的任务也不计入按档位、按模型/深度、按宿主/通道和总体的 actual/est 用时比（备注列写“用时比排除矛盾 run 的 N 条”），所以“估时偏乐观”“可能存在降档空间”这两类用时信号不受它影响。一次通过率、升档率、成本等与时间无关的统计照常包含这些任务。
  - “加速比偏低”信号只在加速比 < 1.3、且加速比上限 ≥ 1.3（任务图本来允许并行）时给出；没记 critical_path_min 的 run 不判断。
- 总览的“缺记录任务数”：run 的 `tasks` 减去实际有记录的任务数（不为负）。
- 计划预估 vs 实际（有 `plan_tier` 的任务才出这一节）：`tier` 与 `plan_tier` 一致、偏低（实际档位更高）、偏高的比例，以及一次通过率；n ≥ 5 且偏低或偏高超过 30% 时给出信号，提示调整 `/hq-plan` 的打分说明。
- 分片、分层校验与合入（4b，有分片任务或 merge 记录的 run 才出）：并行效率 = 各片 actual_min 之和 ÷（片数 × 最长片）；掉队比 = 最长片 ÷ 中位片；并发利用率 = `max_concurrency` ÷ `concurrency_limit`；单元耗时估算误差 = |（actual_min − overhead_min）÷ 单元数 ÷ unit_min_est − 1| 的中位数；全量测试次数 = merge 的 `full_test` + 子会话 `test_scope: full`，每次全量覆盖片数 = 两次全量之间合入的片数均值；合入组数、每组片数、校验次数；建议片数（JSON `suggest_shards`）。
  - **建议片数**与 `scale.py shards`（`shard_plan`）用同一公式（`tests/test_metrics_scaleout.py` 对随机输入核对两者一致）：units = 各片 `units_actual`（没有用 `units_planned`）之和，unit_min = 实测单元耗时中位数，overhead_min = 各片 `overhead_min` 中位数（没有记录时 8；实测为 0 就用 0），target_min = run 的 `target_shard_min`（没有时 40），limit = `concurrency_limit`，reserve = `reserved_slots`（没有时 0），max_overhead_ratio 同名字段（没有时 0.3）：
    ```
    work = units * unit_min
    by_target = max(1, ceil(round(work / target_min, 9)))
    usable = max(1, limit - reserve)
    n = max(1, min(usable, by_target, units))
    while n > 1 and overhead_min / (work / n + overhead_min) > max_overhead_ratio + 1e-9: n -= 1
    ```
    实测单元耗时中位数 ≤ 0、没有 `concurrency_limit` 或没有单元数时为 null。
- 信号（片数 ≥ 2 的 run）：并发利用率 < 50%（附“下次切成 N 片”）、掉队比 > 2、全量测试 > 0.5 次每片（附“每 N 片合入后跑一次”）、单元耗时误差 > 50%。比较都留 1e-9 容差：恰好等于阈值（如误差中位数算出 0.5000000000000002）不触发。
- 按插件版本（3f）：按**运行时生效的版本**分组——`plugin_version_at_start` 能解析出 X.Y.Z 时用它，没有或解析不出（如 `dev`）时用 `plugin_version`。版本号按 X.Y.Z 规范化后分组（`v0.11.0`、`V0.11.0`、`0.11.0` 是同一行；都解析不出时按原字符串，没有为 `unknown`）；所有 run 都没有版本（只有 `unknown` 一行）时不出这一节。`--since-version`/`--before-version` 和 `--check-changelog` 的 since/before 切分都用同一口径。每个版本的 run 数、task 数、一次通过率、返工率、漂移率、验证到位率、漏网问题/任务（integration + user）、actual/est 中位数、平均 cost_usd。每行另有 `ratio_n`、`cost_n`（actual/est 中位数、平均 cost_usd 实际用到的任务数）；actual/est 排除数据矛盾 run 的任务，与 3a 相同。`--since-version V` 只看 ≥V 的 run，`--before-version V` 只看 <V 的；给了任一项时，没有版本号的 run 被排除。V 解析不出 X.Y.Z（如 `0.11`）时报错退出，不会静默忽略。
- 按验证级别（3g）：每级的验证到位率、漏到合并/漏到用户的问题数每任务、漏网 major 数、返工率。所有任务都没有 `verify_level`（只有 `unknown` 一行）时不出这一节。n ≥ 5 且漏网 > 0.3 个/任务，或出现漏网 major 时给出信号。
- 按规则标记（3h）：notes 里只识别前后不紧挨英文字母、数字、`_`（前面也不能是 `:`）的标记，`not rate_limited_at_all` 不算。每个 flag 的一次通过率、返工率、升档率、平均 cost_usd，另有“(无标记)”基线行。规则 9 上调的任务（n ≥ 5）一次通过率 100% 且返工 0、规则 11 授权降档的任务（n ≥ 3）一次通过率 < 60% 时给出信号。
- 常驻模式推荐（6c）：按（项目，`started_at`，`standing_seq`）排序后，同一项目、`standing_seq` 连续的两批算前后批（`started_at` 相同或缺失时按序号，与文件顺序无关）；推荐过（前一批 `recommended_next` > 0）的批数、下一批 `from_recommendation` 为真的批数、采纳率、完工声明数（`recommended_next` 是数字 0；`false` 不算）。推荐过 ≥ 5 次且采纳率 < 30% 时给出信号。
- 待修追踪（6e，v0.3.3；有 `followups` 时才出）：待修项总数、未修数（`fixed_in` 为 null、空串或缺失）、已修数（`fixed_in` 是非空字符串），并列出未修项（`[run_id/task_id] desc`）。JSON `followups`：`total`、`open`、`fixed`、`open_items`。
- 调档与检查点：升档任务数、其中 `checkpoints`>0 的比例（近似“升档由检查点触发、而不是等失败”）、checkpoints / handoffs / derived_tasks 合计、`user_manual_adjust` 次数。

### 信号的可信度与数据覆盖（v0.12.0 起）

- **字段覆盖率（1b）**：est_min、actual_min、tokens、cost_usd、tier、verify_level、verify_pass、review_outcome、attempts、issues、score、independent_review、review_wait_min 各自“有有效值”的任务占全部任务的比例。有效值指类型和取值合法：数字字段是有限数字，`tier`/`verify_level`/`review_outcome` 在取值表内，`verify_pass` 是布尔或 `"partial"`，`issues` 至少有一个数字计数，`score` 至少有一维是 0/1/2，`independent_review` 是带布尔 `ran` 的对象，`review_wait_min` 是 ≥ 0 的数字。JSON 报告的 `coverage` 含 `fields`（每个字段的 `n`、`rate`、`sparse`）和 `joint`（`est_min+actual_min`、`attempts+review_outcome` 两个组合的覆盖率）。
- **`data: "sparse"`**：信号依赖的字段覆盖率 < 50% 时，信号加 `data: "sparse"`、`data_field`、`data_coverage`，md 末尾标“（数据不足：<字段> 覆盖 x%）”。依赖关系：一次通过率类依赖 `attempts+review_outcome`；用时比类依赖 `est_min+actual_min`；加速比偏低依赖 `actual_min`；3i 信号依赖 `score`；规则 9/规则 11 的 flag 信号依赖该 flag 分组的 `attempts+review_outcome`；计划预估偏低/偏高依赖 `tier`（在有 `plan_tier` 的任务里算）；验证级别漏网信号依赖 `issues`；6d 信号依赖 `independent_review`；审核等待信号依赖 `review_wait_min`。按档位/模型的信号用该分组自己的覆盖率，其余用全部任务的。信号仍保留。
- **`confidence`**：所有基于比例的信号（一次通过率 < 60%、risk=low 任务一次通过率 100% 的降档空间、计划预估偏低/偏高 > 30%、规则 9/规则 11 标记的通过率、推荐采纳率 < 30%、3i 升档率偏高、6d 有发现比例 < 10%）加 `confidence`、`ci`（Wilson 95% 区间 `[下限, 上限]`）、`threshold`。区间整体落在越界一侧（“低于”类的上限 < 阈值，“高于”类的下限 > 阈值）为 `"strong"`，跨过阈值为 `"weak"`，md 末尾标“（弱：95% 区间 a–b 跨过阈值）”。“一次通过率 100%”这类信号的阈值取 80%（下限 > 80% 才算 strong），样本少时（约 n<17）几乎总是 weak；3i 的阈值是“该维度其他取值的升档率 + 30 个百分点”。weak 的信号仍然保留在列表里，复盘时只有 `strong` 的当改进建议依据，weak 的只作线索。非比例信号（用时比、加速比、审核等待、掉队比等）没有 `confidence`。
- 按档位、按模型两张表在一次通过率旁边加了“95% 区间”列（JSON 里是各分组的 `first_pass_ci`、`first_pass_k`）。

### 打分维度、独立审核、审核等待（v0.12.0 起；旧数据没有这些字段时不出对应小节）

- **3i 按打分维度**：每个维度（scope/ambiguity/context/risk/verify）的每个取值（0/1/2）的 n、一次通过率、升档率（各带 95% 区间）。信号：某维度某取值 n ≥ 5 且升档率比该维度其他取值（合并计算）高 30 个百分点以上 → “维度 X=v 的任务升档率偏高，打分可能低估了这一维”。该维度没有其他取值的记录时不判断。JSON：`by_score`（`{维度: [{value, n, first_pass_*, escalation_*}]}`，没数据是 `{}`）。
- **6d 独立审核**：只统计 `ran` 为 true 的任务，按 `trigger` 分组（不在枚举内的算 `other`）：触发次数、有发现（`findings` > 0）的次数和比例、发现总数、其中 major 数；标题里另注 `ran` 为 false 的记录数。信号：某 trigger n ≥ 5 且有发现比例 < 10% → “这一触发条件几乎发现不了问题，可考虑放宽”。JSON：`independent_review`（`ran`、`not_run`、`by_trigger`，没数据是 `{}`）。
- **审核等待**：每个 run 里有效 `review_wait_min` 的个数、中位数、最大值，写进效率表（4 节）的“审核等待中位数/最大”两列（有任一 run 有数据时才出这两列；JSON 在 `efficiency[*]` 的 `wait_n`/`wait_median`/`wait_max`）。信号：某 run n ≥ 3 且中位数 > 15 分钟 → “交付后平均 X 分钟才审核，巡检间隔偏长”。

## CHANGELOG 验收判定（`metrics.py --check-changelog CHANGELOG.md`）

每条改动除了自由文本的“验收指标”，再写一行机器可判定的“验收判定”：

```markdown
- **验收判定**：`<路径> <比较> <数值> [n>=<最少样本>] [since=<版本>] [before=<版本>]`；`…`
```

- **路径**是 `metrics.py --format json` 报告里的字段，用点连接：`quality.overall.rework_rate`。列表用 `[字段=值]` 选一项（`by_tier[key=T2].first_pass_rate`、`efficiency[run_id=r2].speedup`），或用 `[*]` 配合聚合函数 `median`/`mean`/`max`/`min`/`sum`（`median(scale_out[*].straggler_ratio)`）。
- **比较**：`<=`、`>=`、`<`、`>`、`==`、`!=`，都带 1e-9 容差（`sum(c[*].x) <= 0.3` 在 0.1 + 0.2 = 0.30000000000000004 时判达到；`<`、`>` 恰好等于时判未达到）。
- **样本 n**：按读的字段取对应的有值数——`ratio_median` → `ratio_n`，`avg_cost_usd`/`cost_per_est_min` → `cost_n`，`avg_tokens` → `tokens_n`，`low_norm_ratio_median` → `low_norm_ratio_n`，`low_first_pass_rate` → `low_n`，`unit_est_*_median` → `unit_est_n`，`wait_median`/`wait_max` → `wait_n`，`acceptance_rate` → `offered`；其他字段取所在对象的 `n`，再依次 `tasks`、`shards`、`offered`；所在对象都没有（如 `adjust.escalated`）时用 `overview.tasks`。聚合时 n 是有值的项数。默认至少 3。
- **since**：只用这个插件版本及以后的 run 计算；条目在 `## vX.Y.Z`（或 `## [X.Y.Z]`）下时默认就是这个版本，在“未发布”下（或在第一个 `## ` 之前、在解析不出版本的标题下）要写明即将发布的版本号，没写的判“无法解析”。since/before 解析不出 X.Y.Z 时也判“无法解析”，不会退回用全部数据。
- **解析**：` ``` `/`~~~` 代码块里的内容（包括其中的 `##`、`###`）忽略。状态行取开头的“待验证 / 已验证 / 已撤回”（`**待验证**`、`待验证，自测通过`、`待验证（…）` 都算待验证）。验收判定可以写成多行，续行一直收到下一个 `- **`、标题或空行。判定文字以“不适用”开头时没有表达式；否则只把能解析或含比较符号的反引号片段当表达式（`` `scale.py shards` `` 这类提及忽略），一个都没有时全部当表达式（判“无法解析”）。
- 只判定状态为“待验证”的条目。每条判定给出“达到 / 未达到 / 样本不足 / 无法解析”，整条：任一未达到（或质量护栏触发）→ 未达到；否则任一无法解析 → 无法解析；全部达到 → 达到；否则样本不足。
- **质量护栏**：对条目里每组不同的 since/before 分别算：since 之前的 run 与 [since, before) 的 run 各有 ≥ 5 个任务、且改动后返工率比之前高出**超过** 5 个百分点时，整条判为“未达到”（不能拿质量换别的指标）。按整数比较，恰好高 5 个百分点（如 7/20 → 8/20）不触发。缺文件时报错退出。

## 保存进仓库与脱敏导出

- **保存**：`scripts/runs-persist.sh save branch` 把 `.hq/runs/*.jsonl` 原样写到专用分支 `hq/runs` 的 `runs/` 下（只追加，每次运行一个文件，多个会话同时写不冲突）；`fetch` 取回到 `.hq/runs-archive/`。同一次运行在几个目录里都有时，`metrics.py` 按 `run_id`+`task_id`（merge 记录按上面“通用规则”的口径）去重。
- **脱敏导出**：`metrics.py <目录…> --export-anon [--raw]` 先把每条记录按白名单裁剪，再汇总：
  - 保留：task 的 `kind`、`risk`、`tier`、`plan_tier`、`host`、`channel`、`verify_level`、`review_outcome`（不在取值表内的写 `other`），`model`（只保留已知厂商或模型族前缀的形状，如 `claude-`、`gpt-`、`gemini-`、`deepseek`、`kimi`、`haiku`/`sonnet`/`opus`、`codex`，可带 `<cli>:` 前缀；含 24 位以上连续字母数字的写 `other`；其他写 `other`）、`assist`（只保留 codex/kimi/claude/opencode/gemini/cursor，其他写 `other`），`effort`（只允许 minimal/low/medium/high/xhigh/max/none，否则写 `other`），`task_type`、`test_scope`、`shard_group`（只留有没有），各数字字段、布尔字段，`issues` 的三个计数和 `severity_max`，`tier_changes` 的 `from`/`to`；run 的 `host`、各数字和布尔字段、`plugin_version`、`plugin_version_at_start`（规范化成 X.Y.Z，后缀丢弃，解析不出写 `other`）；merge 的计数、数字和布尔字段。`verify_pass` 为 `"partial"` 时原样保留。枚举字段的值不是字符串（列表、对象）时一律写 `other`（或 null），不会让导出失败。
  - `flags`（含从 notes 识别出的）只保留已知规则标记：`bias:+1(tier)`、`bias:+1(effort)`、`downgrade:user_allowed(-N)`（N 最多两位）、`rate_limited`、`assist_auto_models`、`tier:not-applied`；带后缀的三种只保留白名单后缀，其他后缀压成 `<前缀>:other`：`billing:` deepseek/kimi/moonshot/codex/openai/anthropic/claude/gemini/other，`effort_env:` minimal/low/medium/high/xhigh/max，`assist_unavailable:` rate_limited/cli_missing/cli_unavailable/no_key/missing_key/auth/quota/timeout/network/same_as_host/other。其他写法丢弃。
  - `found_issues` 每项只保留 `severity`（`minor`/`major`，其他写 `other`）和 `origin_task_id`（换成本 run 内的序号；不在本 run 或指向审核任务自己的写 null），即只剩严重程度和个数。
  - `followups` 只保留计数：每项变成 `{"fixed_in": "fixed"}` 或 `{"fixed_in": null}`，`desc` 和原 `fixed_in` 文本丢弃。
  - `score` 每一维只保留整数 0/1/2（其他写 null）；`independent_review` 只保留 `ran`（布尔）、`trigger`（枚举，不在内的写 `other`）、`findings`、`major`（数字）；`review_wait_min` 按数字字段保留。
  - 改写：`run_id` 换成哈希（`r-` + 10 位），`task_id` 换成本 run 内的序号，`started_at`/`ended_at` 只留日期，`verify_evidence` 只留“有没有”（`[redacted]` 或空）。
  - 删除：`title`、`project`、`goal`、`notes`、`drift_note`、`tier_changes.reason`、merge 的 `shards`（只留个数）/`reasons`/`culprits`/`conflicts`，和所有未知字段；旧数据里的 monitor 记录不导出。
  - 与原始数据的差异：导出里没有 `project`，所以汇总里的常驻推荐（`recommendations`）可能把不同项目、序号相邻的批次配成前后批；按项目看推荐采纳率要用原始数据。
