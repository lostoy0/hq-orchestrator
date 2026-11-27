# 规模化执行：按工作量分片、分层校验、批量合入与主动监控

本文是 `SKILL.md` 第 2、5、7、8、9 步中“分片任务”的完整规则。可执行的版本是同目录的 `scripts/scale.py`：
规则一律调脚本算，不要手算；脚本的输入输出都是 JSON，单元测试见 `tests/test_scale.py`。

**分片任务**指同一种工作单元要做很多遍的任务：页面巡检、路由回归、批量改文件、跑测试用例、翻译条目。
小任务（一两步能做完，或总工作量不到约 30 分钟）不分片，片数下限是 1。

起因（一次真实运行）：前端原型全站带点击巡检，按业务模块切成 4 片、每片 150 页以上，片内基本串行，
每片跑了 2.5–4 小时，并发上限 20 只用了 4；两片各写了一份功能重叠的浮层巡检脚本，两片改了同一个共享页面文件，
合入冲突；每片在自己的容器里跑全量测试（84 个文件、2,500 多个用例），合入后又跑一遍；
有一片的中间提交写了“交付段待补记”，被误判成已交付。

## 1. 片数：按工作量算，不按模块数

1. **估工作量**：工作单元数（页面、路由、文件、用例…）× 单元耗时，加每个子会话的固定开销
   （克隆、装依赖、构建，通常 5–10 分钟，默认 8）。单元耗时拿不准时：先派一个小样本（3–5 个单元）测出来，
   或用 `.hq/runs` 里同类任务的 `unit_min_est` / 实际值（`metrics.py` 报告 4b 节的单元耗时误差）。
2. **算片数**：`scale.py shards --units <N> --unit-min <X> --overhead-min <O> --target-min <T> --limit <L>`。
   - 目标单片时长 `T` 默认 40 分钟（PLAYBOOK `scale_out.target_shard_min`，建议 30–45）。
   - 可用槽位 = 并发上限 − ⌊上限 × 20%⌋：留出的槽位给掉队再拆、共享文件修复会话、前置会话。上限 ≤4 时不留。
   - 片数 = min(可用槽位, ⌈总工作量 ÷ T⌉, 单元数)，至少 1。
   - 固定开销超过单片时长的 30%（`scale_out.max_overhead_ratio`）时，逐片减少，直到不超过或只剩 1 片。
   - 例：600 单元 × 1.5 分钟、T=40、上限 20 → ⌈900/40⌉=23，可用 16 → **16 片**，每片约 64 分钟，整批约 1 小时；
     按模块数切成 4 片则每片 3.8 小时。
3. **怎么切**：按工作单元清单均匀切（`--units-file` 每行一个单元，可带 TAB 权重，输出连续、权重均衡的分配），
   不按业务模块的自然边界切：大模块拆成几片，几个小模块合成一片。语言、平台、角色等正交维度也可以作切分轴。
4. **派发前告诉用户**（一两句话）：总工作量估算、片数、预计每片时长和整批完成时间、为什么是这个片数（脚本的 `why`）。
5. 并发上限、巡检间隔遵守 PLAYBOOK，脚本只在上限之内算，不放宽。

## 2. 共享工具先行

规划时检查各片会不会都用到或改到同一批共享文件（共享脚本、测试工具、公共组件、fixtures）。
会的话，先派一个**前置会话**把共享工具改好（断点续跑、超时重试、通用的健壮性处理等），合入主干后再放开分片。
分片说明里写明：“共享工具 `<路径>` 已就绪，不得另起一份；缺功能写进报告的 DERIVED，不要自己加。”

## 3. 共享文件归属

- 跨分片的共享文件指定**唯一归属**：归某一片，或归一个专门的修复会话。台账任务表的“归属”列写清，
  分片说明的“禁止修改”里列出。
- 其他分片碰到要改共享文件的问题，只在报告里登记（`SHARED_FIXES: <文件>: <问题与建议改法>`），不直接改。
  所有分片交付后，由修复会话集中处理。
- `merge-group` 的 `owners` 传入这张归属表：非归属片改了归属文件会被推迟（`touches_owned_file`），主会话剥离那部分改动或交给修复会话。
- 合入时仍有冲突：汇报里写冲突文件和取舍。

## 4. 进度速率与掉队处理

- **进度格式**（分片说明里约定）：子会话每完成约 10% 的单元，在消息或日志里输出一行
  `HQ-PROGRESS done=<已完成> total=<总数> rework=<返工轮数> failed=<失败单元数>`；W 通道写进日志。
  也可以写进度文件（JSON，同名字段）。主会话用 `scale.py progress` 取最后一行。
- 每次巡检：`scale.py straggler --free-slots <剩余槽位> --target-min T --overhead-min O` 输入各片
  `{id, started_at|elapsed_min, est_min, done, total}`，得到速率、剩余时间、预计总时长。
- **再拆**：预计总时长 > 2 × 预估，**且**剩余工作 > 2 × T 时，提出把剩余单元拆给 k 个新会话（原片保留一份），
  说明代价（k × 启动开销）和预计节省；k 受剩余槽位限制。PLAYBOOK `scale_out.auto_resplit: true` 时直接执行，否则作为建议汇报。
  执行方式：给原片发消息“只做到第 m 个单元为止，之后提交交付”，新会话按 `split` 给的区间接手。
- **快完成的不拆**：剩余 ≤ 2 × T（`near_done`），重新启动的开销会抵消收益。
- 没有空槽位时只汇报（`straggler_no_free_slot`）。

## 5. 分层校验

| 层 | 谁 | 跑什么 |
|---|---|---|
| 关联校验（默认） | 子会话 | 类型检查 + 与改动文件相关的测试：`vitest related <改动文件>`、`jest --findRelatedTests`、按包过滤（`pnpm --filter <包> test`）、`pytest <对应测试目录>`，或项目已有的受影响分析工具（nx affected、turbo --filter…）。交付时在 VERIFY 里列出实际跑了哪些测试 |
| 升级为全量 | 子会话 | 只在改了被大量依赖的共享基础文件（公共组件、测试工具、构建配置、全局状态、依赖清单），或项目规则要求时。规划时 `scale.py test-scope --changed <归属文件> --foundation <PLAYBOOK shared_foundation>` 判断，写进该片说明 |
| 合入后校验 | 主会话 | 每组合入后：类型检查 + 各片改动并集的关联测试，一次 |
| 全量测试 | 主会话 | 只在检查点：一批全部合入后；累计合入达到 `full_test_every_shards`（默认 4 片）或改动行数/文件数超过 `full_test_every_lines`（1500）/`full_test_every_files`（60）；推到主干或发布前；项目 CI 规则要求的检查点。`scale.py full-gate` 判断 |

原有的验证分级（doc/code/high/e2e）不变：分片任务的 code 级就是“关联校验”。

## 6. 巡检时批量合入

1. 每次巡检，把这一轮发现的**所有**已交付分片（交付判定见第 8 节）作为一组，运行
   `scale.py merge-group`（输入 `delivered:[{id, files, depends_on}]`、`pending:[{id, eta_min}]`、`owners`）。
   它按依赖排序，推迟改动文件重叠的、依赖未交付工作的、改了别人归属文件的分片。
2. 预计几分钟内还有分片交付（`pending` 的 `eta_min` ≤ `merge_wait_max_min`，默认 10）时，可以先等 `wait_min` 再合，
   攒到一起；等待只做一次，不为攒批反复拖延。
3. 依次合入组内分片，然后**一次**校验：类型检查 + 各片改动并集的关联测试；这一轮也到了全量节点就只跑一次全量。
4. 一起校验失败：`scale.py locate` 输入 `group` 和失败的测试文件或模块路径，按改动范围定位到具体分片
   （同文件 > 同名测试文件 > 最深的共同目录）。只回退或修复那一片，其余照常合入；定位不到时按 `next.bisect` 二分回退复测。
5. 汇报写清：这一组合入了哪几片、跑了哪些校验、为什么这次没跑或跑了全量（`full-gate` 的 `reasons`）。
6. 每组写一条 `type:"merge"` 记录（见 `metrics-schema.md`）。

## 7. 主动监控

每次巡检顺带计算，不另起常驻进程。监控只读：除下表第一级处置里列出的动作外，不因告警执行其他外部操作。

### 7.1 指标

| 指标 | 数据来源 | 注意 |
|---|---|---|
| `duration_ratio` 执行时长 / 预估 | 子会话创建时间、事件流最新事件时间、交付时间；预估来自第 1 节 | 会话列表的“最后更新时间”可能几小时不刷新（实测一个仍在运行的会话停在两小时前），一律以**事件流里最新事件的时间**为准（B：`list_events` 最新一条的时间） |
| `idle_min` 空转时长 | 最近一次助手事件距现在多久 | 只有进度（`done`）与上次巡检相同时才算空转：后台长任务等结果时也会显得空闲 |
| `cost_ratio` 花费 / 单片预算 | worker_usage 的 `cost_usd`；预算 = PLAYBOOK `budget_usd` ÷ 片数，或 `monitor.shard_budget_usd` | |
| `rework` 返工轮数 | 进度行的 `rework`、修复后复测轮数、同一问题反复出现、被提醒次数、被退回或重新派发 | |
| `failure_rate` 失败率（批次） | 交付时自测失败、合入后校验失败、合入冲突 | 合入端由主会话自己记 |
| `straggler_ratio` 掉队比（批次） | 最长片时长 ÷ 中位片时长 | |

### 7.2 阈值（初始默认，PLAYBOOK `monitor.thresholds` 可覆盖）

| 指标 | 触发 | 严重（立即触发） |
|---|---|---|
| duration_ratio | > 2 | ≥ 4 |
| idle_min | > 40 且进度没变 | — |
| cost_ratio | > 1 | ≥ 2 |
| rework | ≥ 2 | — |
| failure_rate | > 20% | ≥ 50% |
| straggler_ratio | > 2 | — |

至少**连续 2 次巡检**都超过阈值才算触发；严重级别立即触发。触发后计数清零，要再连续超过才会再触发。

### 7.3 两级处置

- **第一级：当场处置**（只处理当前批次，基本不额外花钱）：空转 → 发消息提醒；掉队且剩余够多 → 再拆（第 4 节）；
  失败 → 定位到具体分片（第 6 节第 4 条）；花费超限 → 暂停该分片并问用户；返工 → 发消息让它复查说明里的验收标准。
- **第二级：分析 hq 能否优化**（一次轻量的 `/hq-retro`）。只在两种情况下进入：同类问题（指标 + 根因类别相同，
  即同一个 `key`）跨分片或跨批次重复出现；或者达到严重级别。产出：根因、“能否通过优化 hq 避免”的结论，
  能避免时附一段可以直接发到 hq 仓库执行的改进提示词（格式同 `/hq-retro` 的提示词模板）。不自动修改插件本身。
  根因类别：在 snapshot 的 `cause` 里给（如 `uneven_split`、`shared_tool_missing`、`flaky_env`），没给就按指标的默认类别。

### 7.4 分析限频

- **去重**：`key` = 指标 + 根因类别。同一 key 在冷却期（`monitor.limits.cooldown_min`，默认 120 分钟）或本批次内只分析一次，
  再次触发只累加计数，写进下一次分析。
- **全局上限**：第二级分析默认每批最多 1 次（`per_batch`）、每天最多 3 次（`per_day`）。超出的只记录，留到批次结束时的复盘统一处理。
- **攒批**：非严重的触发不立即分析，批次结束（snapshot `batch_done: true`）时合并成一次分析。只有严重级别才立即分析。
- **不抢资源**：分析放在当次巡检的合入和校验之后，用 T1/T2、低思考深度，单次花费上限 `analysis_budget_usd`（默认 0.5）。
  正在大量合入或跑全量测试时（snapshot `heavy_ops: true`）顺延到下一次巡检。
- **记账**：`scale.py monitor` 输出的 `records` 原样追加进 `.hq/runs/<run_id>.jsonl`（`type:"monitor"`），
  分析结束后补上 `analysis_cost_usd`。状态文件 `.hq/monitor-state.json` 由脚本读写。
  `label` 字段在批次结束后由 `scale.py label` 和独立审核者填（第 9 节），主会话不自己填。

### 7.5 拆分合理性

规划时的片数和切法都依赖估算，估错了，所有片会一起变慢，单片规则看不出来。所以监控里还有四项批次级检查，
由 `scale.py monitor` 从 snapshot 里已有的进度数据直接算，不用调用方另传：

| 指标 | 怎么算 | 默认阈值 | 第一级处置 |
|---|---|---|---|
| `split_unit_error` 单元耗时估错 | 完成 ≥10% 的分片里，实测单元耗时 ÷ `unit_min_est` − 1 的中位数（取绝对值）；至少 3 片、且 3/4 以上偏向同一边才算 | > 0.5；≥ 1.5 为严重 | `replan_remaining`：用实测单元耗时按第 1 节重算剩余工作的片数，给出要新开几个会话 |
| `split_uneven` 预计完成不均 | 各片预计总时长（已交付的用实际时长）的“最晚 ÷ 中位”，不等分片跑完；至少 3 片 | > 2 | `replan_remaining`：把慢片的剩余单元拆出去，或把快片合并 |
| `split_underused` 槽位闲置 | 运行中片数 ÷ 剩余工作能用上的片数（可用槽位、⌈剩余分钟 ÷ T⌉、剩余单元数三者取最小）；剩余工作 ≤ 2 × T 时不算 | < 0.5（越低越差） | `replan_remaining`：按剩余工作补开会话 |
| `split_boundary` 边界冲突 | 有边界信号的分片数：合入时文件重叠被推迟（`boundary.overlap`）、改了归属以外的文件（`boundary.out_of_owns`）、登记了 `SHARED_FIXES`（`boundary.shared_fixes`） | ≥ 2 片 | `review_boundaries`：补指定归属，或派前置/修复会话处理共享文件 |

- 仍按 7.2 的规则触发：连续 2 次超阈值，严重级别立即。每项检查**每批最多处置一次**，避免反复重排；下一批重新生效。
- 第二级分析的 key 是 `split:<原因>`（`unit_time`、`uneven`、`underused`、`boundary`），同样受 7.4 的限频约束。
- 校准同第 9 节；`split_underused` 越低越差，放宽是调低、收紧是调高；整数阈值（`rework`、`split_boundary`）每次至少调 1。
- 做不到的部分：两片“各写了一份功能重叠的脚本”只能靠 `out_of_owns`（在归属以外新建文件）间接发现，功能是否重叠交给第二级分析或审核判断；“当初怎么切才最优”属于事后判断，交给 `/hq-retro`。
- snapshot 为此要带：`target_min`、`overhead_min`、`concurrency_limit`，分片上的 `unit_min_est` 和 `boundary`。

用法：`scale.py monitor --state .hq/monitor-state.json --playbook .hq/PLAYBOOK.md --now <ISO> < snapshot.json`，
snapshot：`{run_id, batch_id, task_type, heavy_ops, batch_done, target_min, overhead_min, concurrency_limit, shards:[{id, task_type, created_at, last_event_at, est_min, done, total, unit_min_est, cost_usd, budget_usd, rework, delivered, boundary:{overlap, out_of_owns, shared_fixes}, cause:{<指标>: <类别>}}], batch:{failure_rate, straggler_ratio}}`。

## 8. 完成判定

不能只在提交正文里搜“交付”两个字。已交付必须满足其一：

- 提交正文或最后一条消息里有一行**小节标题** `## 交付`（任意级别的 `#`，标题只有这两个字，英文 `## Delivery` 也行），
  该小节里有 `STATUS: DONE`，并且 `VERIFY:` 有实际结果（不是空、`none`、`待补`）；
- 或者分片写出约定的完成文件（JSON：`{"status":"DONE","verify":"<结果>", ...}`）。

`scale.py delivered < 正文`（退出码 0 = 已交付）。“交付段待补记”“本次交付了一半”这类中间提交不算。

## 9. 阈值校准

阈值不是一次定死的，每次 `/hq-retro` 或每批结束时校准一次：

- **标记**：`label: effective`（确实发现了问题，或处置带来了收益）、`false_positive`（最终正常完成、处置无收益），
  以及漏报 `{"type":"monitor","event":"missed","metric":…,"task_type":…}`。**主会话不自己打标签**（等于自评，会让校准偏向自己的结论），按下面两步做：
  1. **先跑规则**：`scale.py label < {"records":[这一批的 monitor 触发记录…], "outcomes":{…}}`（一批一次）。
     输出 `records`（规则判定的加 `label`、`label_source:"rule"`、`label_reason`；已有 label 的人工或审核记录原样保留）、
     `unlabeled`（规则判不了的，带 `label_reason` 说明缺什么）、`missed`（按规则补记的漏报，`label_source:"rule"`），
     以及 `history` = `records` + `missed`。整个输出可以直接作为 `scale.py calibrate` 的输入。
  2. **剩下的交给独立审核**：`unlabeled` 交给一个独立审核子代理去标，只给它这些记录和对应的 outcomes 数据，
     不给主会话的看法或倾向；审核者标的记录写 `label_source:"reviewer"`，再并回 `history`。规则之外的漏报审核者可以补，规则不猜。
- **outcomes**：对象，键是触发记录的 `task_id`（按字符串比较，分片 id，批次级指标用 `"batch"`），只填主会话手头已有的数据，不知道的字段不填（对应规则就判不了，进 `unlabeled`）：

  | 字段 | 含义 | 用于 |
  |---|---|---|
  | `est_min` / `actual_min` | 预估时长 / 交付后实际时长（`"batch"` 上是整批计划完成时间 / 实际完成时间） | 时长类、idle、漏报 |
  | `task_type` | 任务类型（不填就取同一 task_id 触发记录上的） | 漏报 |
  | `action_taken` | 是否执行了处置：`"resplit"`、`"replan"` 或 `true`；没执行 `false`；其他值一律视为未知（unlabeled） | 时长类 |
  | `expected_saving_min` / `actual_saving_min` | 再拆 / 重新规划时预计节省（`straggler` 的 `saves_min`）和实际节省 | 时长类 |
  | `progress` | 巡检时的进度序列 `[{ts, done}]`；`reminder_ts` 可覆盖提醒时间（默认取触发记录的 `ts`） | idle |
  | `located` / `culprits` | `scale.py locate` 是否定位到具体分片（只认 `true`）/ 哪几片（非空列表也算定位到） | failure_rate |
  | `rerun_passed` | 失败的校验不改代码重跑即通过（只认 `true`） | failure_rate |
  | `rework_after_message` | 发复查消息后又返工的轮数 | rework |
  | `user_decision` / `final_cost_usd` / `budget_usd` | 用户决定 `stop`、`adjust`、`continue`；最终花费和预算 | cost_ratio |
  | `merge_conflicts` / `ownership_violations` | 合入时冲突次数 / 归属违规（`touches_owned_file` 等）次数 | split_boundary |
  | `verify_failed_groups` / `failure_rate` / `failure_rate_threshold` | `"batch"` 上：合入校验失败的组数、最终失败率、当时阈值（不填用默认 0.2） | failure_rate 漏报 |
  | `by_metric` | `{指标: {字段…}}`，同一主体上不同指标的处置不同时按指标覆盖（如批次上的 `split_unit_error` 与 `straggler_ratio`） | 全部 |

- **规则**（常量在 `scale.py` 的 `LABEL_*`、`MISSED_DURATION_RATIO`；“恰好 50%”“恰好 1.2 倍”按 1e-9 容差比较，不受浮点舍入影响；`records` 不是列表或 `outcomes` 不是对象时退出码 2）：

  | 指标 | effective | false_positive | 其余 |
  |---|---|---|---|
  | duration_ratio、straggler_ratio、split_unit_error、split_uneven、split_underused | 执行了再拆或重新规划，且实际节省 ≥ 预计节省的 50%（恰好 50% 算有效） | 执行了但实际节省 < 50%；或没执行处置、最终实际时长 ≤ 1.2 × 预估（恰好 1.2 倍算正常完成） | unlabeled |
  | idle_min | 提醒后 2 次巡检内 `done` 增加 | 提醒前进度在涨、提醒后也涨，且实际时长 ≤ 1.2 × 预估（在等后台长任务） | 两条同时成立或都不成立：unlabeled |
  | failure_rate | 定位到具体分片 | 重跑即通过（不稳定测试） | 两条同时成立或都不成立：unlabeled |
  | rework | 消息后不再返工 | — | unlabeled |
  | cost_ratio | 用户选择停止或调整 | 用户原样继续，且最终花费 ≤ 1.2 × 预算 | 没有用户决定：unlabeled |
  | split_boundary | 合入时确实出现冲突或归属违规 | 全部干净合入（两项都为 0） | unlabeled |

  漏报：某片实际时长 > 2 × 预估（恰好 2 倍不算），而记录里没有该片的 duration_ratio 触发 → 一条 duration_ratio 漏报；
  `"batch"` 上有合入校验失败、失败率 > 当时阈值，而没有 failure_rate 触发 → 一条 failure_rate 漏报。已有同一主体同一指标的漏报记录时不重复补。
- **调整规则**（`scale.py calibrate`，输入 `label` 的输出或 `{"history":[…]}`）：
  - 误报率 = 误报 ÷（有效 + 误报）> 30% → 放宽；漏报率 = 漏报 ÷（有效 + 漏报）> 20% → 收紧；两者都高 → 不动。
  - 每次调整不超过 20%（整数阈值至少调 1）；每个阈值有上下限（duration_ratio 1.3–4、idle_min 15–120、cost_ratio 1–3、rework 1–5、failure_rate 0.1–0.5、straggler_ratio 1.5–4、split_unit_error 0.3–1、split_uneven 1.5–4、split_underused 0.25–0.8、split_boundary 1–5）。
  - 按任务类型（`task_type`：patrol 巡检、dev 开发、docs 文档、test 测试…）分别维护；同一类型样本少于 5 个时沿用全局值或默认值。
  - 时长类阈值用分布：同类任务实际时长 ÷ 预估的 P90（`ratios`），同样受 20% 步长和上下限约束。
  - 用户手动设定的阈值（PLAYBOOK 授权区 `monitor.thresholds`）优先，不被自动覆盖。
- **写回**：`scale.py calibrate --playbook .hq/PLAYBOOK.md --write` 把结果写进 PLAYBOOK 末尾的
  `<!-- hq:thresholds:begin -->` 区块（版本号、时间、阈值、每项调整前后的数值和依据，以及上一版）。
  下一次派发时把变化告诉用户；`scale.py thresholds --playbook … --rollback` 一键回退到上一版。

## 10. 记录

分片任务的 task 记录、合入组的 `merge` 记录、监控的 `monitor` 记录字段见 `metrics-schema.md`；
`/hq-retro` 用 `metrics.py` 报告 4b、4c 节出并行效率、掉队比、并发利用率、单元耗时估算误差、全量测试次数和耗时、
监控触发与限频统计，以及各阈值的有效率、误报率和漏报数。
