# 更新记录

## 格式说明

按版本倒序。每个版本下面，**每条改动**都写这五项：

- **改动**：改了什么（到文件和段落）。
- **原因/假设**：为什么改；预期会带来什么变化。
- **验收指标**：之后用哪项指标、达到什么数值才算有效（来自 `skills/hq/scripts/metrics.py` 的报告）。
- **状态**：`待验证` / `已验证` / `已撤回`。
- **复盘报告**：对应的 `.hq/retro/<日期>.md`；没有就写“无（人工改动）”。

规则：

- 新改动一律先标“待验证”。`/hq-retro` 用验收指标核对后，才改为“已验证”或“已撤回”。
- 撤回时保留原条目，只改状态，并在原因里写撤回理由，不要删除。
- 改动不能以牺牲质量门槛（不漂移、验证到位、问题少）换取省钱。返工率或问题数上升的改动要撤回。

---

## 未发布

加许可证（Apache-2.0 加 Commons Clause）和仓库配套文件，不改任何技能行为。

### 增加许可证、贡献与安全文档、CI
- **改动**：新增 `LICENSE`（Apache-2.0 官方全文，前面加 Commons Clause v1.0 条件）；`plugin.json`、`marketplace.json` 加 `author`、`homepage`、`repository`、`license`（`SEE LICENSE IN LICENSE`，组合协议没有单一 SPDX 标识）；两个 `SKILL.md` 的 frontmatter 加 `license`（只装技能目录时也能看到许可）；中英文 README 末尾加“许可与商用”一节；新增 `CONTRIBUTING.md`（含贡献授权条款）、`SECURITY.md`、PR 模板、问题报告模板、`.github/workflows/test.yml`（ubuntu 和 macOS 上跑全部自测）。
- **原因/假设**：任何人可以免费使用（含公司内部和商业项目），但不得把本项目打包出售或收费提供托管、咨询、支持；作者自己可以出售和收费支持。贡献条款让作者能把外部贡献放进自己出售的版本。假设：这些文件不影响技能行为，也不影响安装和测试。
- **验收指标**：`tests/` 全部通过（与改动前一致）；CI 在 ubuntu 和 macOS 上首次运行通过。
- **状态**：待验证（macOS 本机自测全部通过；ubuntu 的 CI 尚未运行）
- **复盘报告**：无（人工改动）

---

## v0.5.2（2026-11-25）

`resources.sh` 读不到读数时报 UNKNOWN，不再误报 RED；写明 Codex 作主宿主时的沙箱限制（实测 assist 熔断的结论）。

### resources.sh 读不到读数时报 UNKNOWN；写明 Codex 作主宿主时的沙箱限制
- **改动**：`scripts/resources.sh` 每项读数读不到（`sysctl`、`vm_stat`、`/proc` 被拒或没有）时不再当成 0：输出里记为 `null`，新增 `unreadable` 数组和 `reason` 里的“无法读取:…”；已读到的读数没到 RED 时 `level` 为 `UNKNOWN`、`new_local_slots` 最多 1，读到的读数显示 RED 时仍为 RED；新增测试注入 `HQ_FAKE_UNREADABLE`。`tests/test_resources.sh` 的 `over()` 不再用 `local -n`（macOS 自带 bash 3.2 不支持，原先 4 项失败），新增 7 项 UNKNOWN 用例。`SKILL.md` 第 5 步补 `UNKNOWN` 的处理（按 YELLOW），第 1 步辅助预检补“能否建 worktree”；`calibration.md` 规则 10 的关键路径条件加 `UNKNOWN`；`hosts/codex.md` §5 第 9 条改为实测结论；README 中英文同步。
- **原因/假设**：2026-11-25 在 Codex（0.172.0，`codex exec --approve-for-me`）里实测 assist 熔断：沙箱禁止 `sysctl`，旧脚本把读不到当成 0，报 `RED`/0 槽位，会挡住所有本地派发；同时沙箱禁止写 `.git`，W 通道建不了 worktree、主宿主也提交不了。熔断本身按规则 10 正常工作（`same_as_host` 跳过、缺 `env_file` 和建不了 worktree 都记为不可用、剩余任务全部由 Codex 自己做、`autonomy_stops: 0`）。假设：区分“读不到”和“资源紧张”后，沙箱宿主不会再被误判为 RED。
- **验收指标**：沙箱宿主（Codex 等）的运行里，因 `resources.sh` 误报 RED 而 `throttle_events` > 0 的次数 = 0；`level: UNKNOWN` 的运行里，因资源不足被 stop_worker 的任务 = 0。
- **状态**：待验证（`test_resources.sh` 26/26；在 `codex sandbox` 里实跑：旧脚本 RED/0、新脚本 UNKNOWN/1）
- **复盘报告**：无（人工改动）

## v0.5.1（2026-11-25）

Codex 辅助执行者实机核实与 macOS 修复；选档“拿不准往上选”扩展到所有宿主；辅助执行者停用（熔断）规则，主宿主不再假定是 Claude。

### 辅助执行者：不可用或屡次失败就停用，主宿主不再假定是 Claude
- **改动**：`calibration.md` 规则 10 写明“主宿主”是运行本插件的宿主和模型（不一定是 Claude），profile 与主宿主相同（如 Codex 宿主上的 `codex`）时跳过；新增“停用（熔断）”：不可用（预检不过、worker 起不来、认证失败、限流、额度用完）立即停用，连续失败 2 次或累计失败达到 `assist.max_failures`（默认 2）停用，并定义了“失败”；全部停用时本次剩余任务全部由主宿主执行、按主宿主映射重新选档、不停下问用户，台账头部记 `assist: off（熔断：…）`；常驻模式停用持续到会话结束。`SKILL.md` 辅助执行者一节和第 1 步预检、`playbook-template.md` 新增 `max_failures`、`metrics-schema.md` run 记录新增可选字段 `assist_disabled`、`hosts/codex.md` §5 新增第 9 条、`hosts/kimi.md`、README 中英文、`PROMPT.md` 同步。
- **原因/假设**：用户要求（2026-11-25）：辅助模型不可用、频繁或连续失败时，放弃辅助、全部由主模型执行；插件也会运行在 Codex 等宿主上，不能假定主模型是 Claude。原规则只写“累计失败 2 次跳过”，没写全部停用后怎么办，文案里多处写“主宿主（如 Claude）”，在 Codex 宿主上还可能把 `codex` 当成自己的辅助。假设：熔断后不再反复派给坏掉的辅助，回收浪费下降，总用时不因辅助拖长。
- **验收指标**：开启 `assist` 的运行里，同一 profile 在被停用后仍被派发的任务数 = 0；单次运行里辅助失败任务数 ≤ `max_failures`（不可用导致的除外）；非 Claude Code 宿主上 `assist_skip:*:same_as_host` 之外，没有把主宿主自己的 CLI 当辅助派发的记录。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### 拿不准难度时所有宿主都往上选一步
- **改动**：`calibration.md` 规则 9 从“只对低成本宿主上调一档”改为所有宿主都上调一步：`cost_weight: low` 上调一整档；`high`（如 Claude Code）默认只把思考深度上调一级、模型不变，模糊度 ≥1 或风险 2 时上调一整档；上限一步，不动用 `xhigh`/`max`；notes 标记改为 `bias:+1(tier)` / `bias:+1(effort)`（旧 `bias:+1(cost_low)` 等同 `tier`）。规则 1 补一句指向规则 9。`SKILL.md` 第 3 步、`hosts/codex.md`、`dsh.md`、`deepseek.md`、`generic.md`、`playbook-template.md` 的 `cost_weight` 注释、README 中英文、PROMPT.md 同步。
- **原因/假设**：用户偏好（2026-11-25）：难度评估不太确定时，尽量提高一档模型或思考深度。原规则在 Claude Code 上拿不准仍选最低档，失败重来的代价（重新熟悉项目、交接丢上下文）通常大于差价。假设：高成本宿主只上调思考深度就能拿到大部分收益，花费增幅小于换模型。
- **验收指标**：带 `bias:+1(*)` 标记的任务，一次通过率比同档未上调的任务高至少 10 个百分点（每组至少 5 个任务）；`high` 宿主上调后每任务平均 cost_usd 增幅不超过 30%；返工率不上升。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### Codex 辅助执行者实机核实；修 macOS 上 W 通道起不来、Codex worker 提交不了
- **改动**：`scripts/cli-worker.sh` 启动 runner 时，没有 `setsid`（macOS）就改用 `python3` 的 `os.setsid()` + exec；runner 新增第 5 个参数，后端设 `BE_COMMIT=1` 时，CLI 退出码为 0 且 worktree 有改动，就在沙箱外 `git add -A && git commit` 到 `hq/<id>`（失败只写 `log`）。`scripts/backends/codex.sh` 在 `workspace-write` 下设 `BE_COMMIT=1` 并写 notes，文件头改为“已实机核实”。`tests/fixtures/fake-cli/codex` 按实测事件格式补 `thread.started`、`error` 警告项、`agent_message`、`cache_write_input_tokens`，新增 `FAKE_WRITE`；`tests/test_cli_worker.sh` 新增代提交 5 项用例；`tests/test_install.sh` 的 `wc -l` 去掉 BSD 前导空格。`references/hosts/codex.md` §5 第 1、3、7 条、`references/runtimes.md` W 节 codex 行的核实状态同步更新。
- **原因/假设**：2026-11-25 在 macOS 26.6.2 上用 codex-cli 0.172.0（模型 gpt-6.2-sol）实跑：① macOS 没有 `setsid`，`cli-worker.sh start` 后 runner 根本没起来，状态一直是 `unknown`（`test_cli_worker.sh` 27 项失败）；② Codex `workspace-write` 沙箱把 `.git` 当受保护路径，worktree 里 `git add` 建不了 `index.lock`，worker 无法提交，`--add-dir` 主仓库 `.git` 也无效。`-m`、`-c model_reasoning_effort=low|medium`、`-s read-only|workspace-write`、`--json`、`-` 都被接受（会话记录 `turn_context` 显示生效），usage 字段与 `be_usage` 一致，无需改。假设：代提交后，Codex 辅助任务在 macOS 上能按 `hq/<id>` 分支交付，主宿主照常审核。
- **验收指标**：开启 `assist: [codex]` 的运行里，codex 辅助任务因“分支上没有提交”而回收的次数 = 0；W 通道在 macOS 上 `state: unknown` 的 worker 数 = 0。
- **状态**：待验证（三套自测通过；smoke1c / smoke2 / smoke3 与 3 任务端到端（assist: codex，metrics 出现 3d）已实跑；`danger-full-access` 只在 `--help` 里核对，未实跑）
- **复盘报告**：无（人工改动）

## v0.5.0（2026-11-25）

### 辅助执行者：主宿主主攻难点，Codex / Kimi 承接中低难度
- **改动**：`calibration.md` 新增规则 10“分工路由”；`SKILL.md` 新增“辅助执行者”一节，第 1、3、4、8、9 步和授权配置、台账头部相应补充，支持 `/hq --assist <名单> [--assist-max T0|T1|T2]` 和 PLAYBOOK `assist`；`scripts/cli-worker.sh` 新增 `--env-file`（只注入 worker 进程，文件须 600，值不进 cmd/notes/输出）和 `--label`（写进 status/usage）；新建 `references/hosts/kimi.md`；`metrics-schema.md` task 新增可选字段 `assist`；`metrics.py` 新增“3d 辅助执行者 vs 主宿主”分组，脱敏导出保留 `assist`；`hq-retro` 复盘清单新增第 10 项；README 中英文、PROMPT.md 同步。
- **原因/假设**：用户希望大目标里难的、重要的任务由 Claude 自己做，其余交给 Codex、Kimi 等更便宜的模型并由 Claude 审核，以节省 Claude 额度、加快交付且不降质量。原来的 `worker_clis` 只是“允许用”，选档不会主动分流，也接不了 Kimi。假设：只把需求明确、低风险、易验证的 T0–T2 交出去，审核不降档、失败即收回，质量门槛不变，主宿主 tokens 明显下降。
- **验收指标**：开启 `assist` 的运行里（每组至少 5 个任务）：辅助各档一次通过率与主宿主同档相差不超过 20 个百分点；回收率（辅助任务的交接率）≤ 30%；返工率、合并通过率不劣于未开启时；主宿主侧每任务平均 tokens 下降。
- **状态**：待验证（`cli-worker.sh` 新参数和 metrics 分组已有自测；Kimi 接口、Codex 实际调用未实机运行）
- **复盘报告**：无（人工改动）

### 随 0.5.0 发布的此前未发布改动

补充 B 通道（云端子会话）通信能力的实测结论。只改文档。

### 子会话汇报在 auto 模式下不可用，补降级写法
- **改动**：`skills/hq/references/hosts/claude-code.md` §2 `message_worker` 行补主会话向子会话发消息的实测行为和 `priority` 三档，§5 新增“auto 模式下子会话主动汇报不可用”及巡检识别方法；`runtimes.md` B 通道补“回报可能发不出去”；`brief-template.md` 补“回报发不出去时不要停下，以交付格式和分支为准”；`SKILL.md` 监控一节补“`blocked` 且 `need_input` 多半是在等批准”。
- **原因/假设**：2026-11-25 用 haiku 子会话实测（权限模式继承 auto）：子会话 `send_message` 发给主会话会卡在人工批准上，发给兄弟会话被分类器拒绝，仓库里的 allow 规则和 `extra_allowed_tools` 预批准都没有放行。原文档默认子会话会主动回报，无人值守时会让主会话一直等不到消息。假设：说明里同时要求写交付文件、巡检识别 `need_input`，能让这类卡住在一次巡检内被发现。
- **验收指标**：auto 模式的云端运行里，因子会话等批准而卡住、且主会话超过 2 个巡检间隔才发现的任务 = 0。
- **状态**：待验证
- **复盘报告**：无（人工改动）

---

## v0.4.8（2026-11-25）

用时比信号也排除时间数据矛盾的 run。

### actual/est 排除矛盾 run
- **改动**：`skills/hq/scripts/metrics.py` 先算效率表，再把标了“数据矛盾”的 run 的任务排除在 actual/est 用时比之外：按档位、按模型/深度、按宿主/通道的中位数和总体中位数都不再计入它们；分组新增 `ratio_excluded`，报告备注列写“用时比排除矛盾 run 的 N 条”。依赖用时比的“估时偏乐观”“可能存在降档空间”信号随之不受矛盾数据影响；一次通过率、升档率、成本等照常统计。`metrics-schema.md` 同步说明。`tests/test_metrics.py` 更新断言：fixtures 里 T2、sonnet/medium 的用时比只来自 r2，现在为空且不报“估时偏乐观”，T1 不受影响。
- **原因/假设**：v0.4.7 只让加速比信号跳过矛盾 run，档位和模型的用时比仍在用同一批不可信的 `actual_min`。测试数据里 T2 的“估时偏乐观”信号全部来自 r2，属于误报；真实数据把等审核、合并时间算进 `actual_min` 时，也会把估时偏差夸大，进而误导选档校准。
- **验收指标**：复盘中“估时偏乐观”“可能存在降档空间”信号所依据的任务里，来自矛盾 run 的 = 0；这两类信号给出后经复盘查证属实的比例 ≥ 80%。
- **状态**：待验证
- **复盘报告**：无（人工改动）

---

## v0.4.7（2026-11-25）

加速比口径：识别矛盾的时间数据，减少“加速比偏低”误报，写清 `actual_min` 怎么取。

### 加速比数据矛盾检测与信号收紧
- **改动**：`skills/hq/scripts/metrics.py` 效率表新增“加速比上限”（actual_min 之和 / critical_path_min）和“备注”列；加速比 > max_concurrency × 1.1、或某个任务的 actual_min > wall_min 时备注“数据矛盾”，该 run 不再产生加速比信号，改为提示“时间数据矛盾，先核对 actual_min 口径”；“加速比 < 1.3”信号只在加速比上限 ≥ 1.3（任务图本来允许并行）时给出，没记 critical_path_min 的 run 不判断。`metrics-schema.md` 写明 `actual_min` = 从派发到 worker 交付的墙钟时间、不含等审核和合并，并补充效率各列与矛盾判定；`runtimes.md` 的 worker_usage 加通用取法（W 取 `cli-worker.sh status` 的 `minutes`），`hosts/claude-code.md` 加 B 通道取法（`created_at` 到交付那一轮结束）。`tests/test_metrics.py` 更新 r2（矛盾）、r3（无关键路径不报）的断言，新增串行依赖链不报、可并行却串行执行要报、容差边界的测试。
- **原因/假设**：2026-11-25 云端复盘中，子代理发现测试数据 r2 加速比 3 而 max_concurrency 只有 1，怀疑公式有误。核实后公式正确（平均同时在跑的任务数），是数据自相矛盾：1 个并发下 3 个任务合计 90 分钟、单个任务 40 分钟，都超过整批 30 分钟。真实运行里如果 `actual_min` 把等审核、合并的时间算进去，会出现同样的虚高，而原报告不会提示。另外，原“加速比偏低”信号在串行依赖链上必然触发，是误报。
- **验收指标**：真实运行的复盘里，标“数据矛盾”的 run 占比在口径写清后的 5 次运行内降到 0；“加速比偏低”信号给出后，复盘确认属实（确有可以并行却没并行的任务）的比例 ≥ 80%。
- **状态**：待验证
- **复盘报告**：无（人工改动；起因见 2026-11-25 云端 hq-retro 验证）

---

## v0.4.6（2026-11-25）

运行记录可以保存进项目仓库，云端跨会话也能复盘；可以手动导出脱敏数据分享给插件作者。

### 运行记录保存进仓库
- **改动**：新增 `skills/hq/scripts/runs-persist.sh`：`save branch` 用 git 底层命令把 `.hq/runs/*.jsonl` 写进专用分支 `hq/runs` 的 `runs/` 下并推送（不碰工作区和当前分支；只追加；别的会话同时推送时重新拉取再试，最多 3 次；推不上退出码 3）；`save commit` 只把记录文件提交到当前分支；`fetch` 取回到 `.hq/runs-archive/`。`SKILL.md` 第 9 步删去“云端不需要保存”，按 PLAYBOOK 新项 `runs_persist: off|branch|commit` 保存，`branch` 推不上就降级为 `commit` 并改写 PLAYBOOK；云端没写这项时在第一次汇报里问一次。授权配置、`playbook-template.md` 加 `runs_persist`。`hq-retro` 第 1 步先 `fetch` 再把 `.hq/runs-archive` 一起汇总。新增 `tests/test_runs_persist.sh`（26 项）。README 中英文加“运行记录与数据分享”一节。
- **原因/假设**：云端容器回收后 `.hq/runs/` 丢失（2026-11-25 云端实测 `/hq-retro` 只看到本会话数据），主要在云端使用的项目永远凑不够复盘门槛。存进项目仓库后数据和代码在同一信任范围，不涉及第三方。
- **验收指标**：开了 `runs_persist: branch` 的云端项目，`/hq-retro` 的 run 数等于实际运行过的批次数（缺失 = 0）；`runs-persist.sh` 推送失败后降级为 `commit` 的次数单独记进 notes，比例不应超过 50%（超过说明云端默认应改为 `commit`）；保存步骤导致的 `autonomy_stops` 只有云端首次那一次。
- **状态**：待验证（本地用 bare 仓库测过并发、降级和取回；2026-11-25 云端会话实测 `save branch` 推送 `hq/runs` 成功、`fetch` 取回成功，但云端删不掉远程分支，测试分支需手动删除）
- **复盘报告**：无（人工改动）

### 手动导出脱敏数据
- **改动**：`metrics.py` 加 `--export-anon [--raw]`：先按白名单裁剪每条记录再汇总，只保留枚举、数字、布尔字段，删掉 `title`、`project`、`goal`、`notes`、`drift_note`、`tier_changes.reason` 和未知字段，`run_id` 哈希、`task_id` 换序号、时间只留日期、`verify_evidence` 只留有无；非法枚举和不合规的 model/effort 写 `other`。`hq-retro` 加 `/hq-retro --export`：完整显示导出内容并存到 `.hq/retro/export-<日期>.json`，由用户自己用新增的 `.github/ISSUE_TEMPLATE/retro-data.md` 开 issue，绝不自动上传；复盘报告末尾只提示一次（PLAYBOOK `share_hint`）。`metrics-schema.md` 写明白名单。`tests/test_metrics.py` 加 3 个测试（导出后指标不变、自由文本和未知字段不泄露、`--raw` 必须配 `--export-anon`）。
- **原因/假设**：插件作者只能看到自己的运行数据，选档校准缺少别的宿主、项目的样本。自动上传无处可传（其他用户没有仓库写权限，PR 和 issue 公开，自建服务要运维且会被云端代理拦），靠模型脱敏也不可靠；改为确定性白名单加用户主动分享，用户每次都能看到传出的完整内容。
- **验收指标**：收到的 retro-data issue 中，含任何自由文本或项目名的 = 0；`share_hint` 提示后用户反馈“被打扰”= 0；出现来自至少 2 个不同宿主的分享后，`calibration.md` 至少有 1 条改动的依据来自分享数据。
- **状态**：待验证
- **复盘报告**：无（人工改动）

---

## v0.4.5（2026-11-25）

新增常驻模式：同一个会话一批接一批地当总指挥，并支持接管已有会话。

### 常驻模式
- **改动**：`skills/hq/SKILL.md` 新增“常驻模式”一节（`/hq --stay`、“常驻司令部”进入，`/hq --stop`、“退出常驻”退出）：批次结束不退出、新目标开新一批（新 run_id，第 0 步照常判断）、提问不退出、上一批仍在跑时新批不能改其归属文件；接管已有会话时把聊天里的进度写进台账“接管背景”；台账头部加 `mode`、`skill_path`、`batch`，每回合发现记不清流程就重读 `skill_path`；每批任务表压成一行移到“历史批次”。description 加常驻触发词。`metrics-schema.md` run 记录加可选字段 `standing_seq`（读取方忽略未知字段，`metrics.py` 不需改）。`PROMPT.md` 加“常驻”一段。README 中英文加“常驻模式”一节，含不重开会话、靠读取 SKILL.md 接管的写法。版本号同步为 0.4.5。
- **原因/假设**：用户常在已积累大量上下文的会话里连续推进多批工作，开新会话要重新交代进度。常驻后不必换会话；状态写在台账里，压缩或换会话后也能接上。
- **验收指标**：带 `standing_seq` 的 run 中，第 2 批及以后的 run 质量门槛（漂移率、验证到位率、返工率）不差于非常驻 run；用户反馈“压缩后不再派子会话 / 忘了常驻”的次数 = 0；常驻 run 的 `autonomy_stops` 中因“接不上之前进度”而问用户的次数 = 0。
- **状态**：待验证（只做了文档改动和现有测试，未在真实会话里跑过多批）
- **复盘报告**：无（人工改动）

### 常驻模式：推荐下一批与完工声明
- **改动**：`SKILL.md` 常驻模式加“推荐下一批”：每批汇报后从台账（待办池、未派衍生任务、BLOCKED/FAILED、后续问题）、会话（接管背景未完成项、总目标未覆盖部分）和项目（路线图、待验证项、TODO/FIXME、open issue、失败测试）收集候选，只保留有来源的，最多 5 条并排序；回复“按推荐”开始，用户说过“按推荐自动继续”时直接开下一批。没有可执行候选且总目标已满足时明确声明“项目当前所有任务都已执行完毕，没有更多可执行任务了”，附检查过的来源。进入常驻时建“总目标”和“待办池”。内容多时派 T0/T1 只读调研，主会话不亲自读。`metrics-schema.md` run 加可选字段 `from_recommendation`、`recommended_next`。`PROMPT.md`、README 中英文、PROMPT.md 同步。
- **原因/假设**：用户不用每批自己想下一步；有证据的推荐减少遗漏，明确的完工声明避免空转或硬编任务。
- **补充（无目标进入）**：`/hq --stay` 不带目标时先探索项目（推荐来源之外补看 README/docs 定位、近 20 条提交、未合并分支、轻量测试和 lint、过期依赖或文档；大项目派 T1 只读调研），给出编号推荐，等用户回复编号、“按推荐”或自己的目标，进入时一律不自动开始；没找到待办时请用户给目标，不说完工。推荐统一编号，可按编号挑选。
- **验收指标**：无目标进入时，用户选用了至少一条推荐的比例 ≥ 50%；常驻 run 中 `from_recommendation=true` 的占比 ≥ 50%（推荐有用）；来自推荐的批次质量门槛不差于用户直接给目标的批次；完工声明后用户又指出“还有没做的既有任务”的次数 = 0。
- **状态**：待验证
- **复盘报告**：无（人工改动）

---

## v0.4.4（2026-11-25）

修复版本：macOS 自带 bash 3.2 下 `install.sh` 无法安装。

### 修复 bash 3.2 下 unbound variable
- **改动**：macOS 自带 bash 3.2 在 UTF-8 locale 下会把非 ASCII 字节当成变量名的一部分，`install.sh` 第 312 行的 `$s（供` 被读成变量 `s\xEF…`，在 `set -u` 下报 `unbound variable` 并退出（用户实测 `./install.sh --host auto` 复现）。把所有紧跟非 ASCII 字符的变量改成 `${var}`，共 14 处：`install.sh`（下载失败、未知宿主、安装计划、安装、完成提示）、`adapters/render.sh`（模板描述、占位符注释、`--check` 提示）、`skills/hq/scripts/backends/{cursor,gemini,opencode}.sh`（忽略 `--effort` 的提示）。生成的模板内容不变（`render.sh --check` 三种格式一致）。`tests/test_install.sh` 加第 33 项回归检查（用 perl 扫描所有 `.sh`，macOS grep 不支持 `-P`），增至 72 项。版本号在 install.sh、两个 Claude 清单、Gemini 清单和 README 的安装命令同步为 0.4.4。
- **原因/假设**：macOS 是主要用户平台之一，默认 bash 就是 3.2；修复后 macOS 上能一次装好，W 通道的 cursor、gemini、opencode 后端在带 `--effort` 时也不会中途退出。
- **验收指标**：`tests/test_install.sh` 全部通过；macOS 自带 bash 下 `./install.sh --host auto` 退出码 0；用户反馈“install.sh 报 unbound variable”的问题数 = 0。
- **状态**：待验证（只在 Linux 的 bash 5 上跑过测试，macOS bash 3.2 待实机确认）
- **复盘报告**：无（人工改动）

---

## v0.4.3（2026-11-25）

本版本让整个仓库可以作为 Gemini CLI 扩展安装，并把 Gemini CLI 升级为原生宿主。依据 GitHub google-gemini/gemini-cli 的官方文档（2026-11-24 的提交：`docs/extensions/reference.md`、`docs/core/subagents.md`、`docs/cli/skills.md`、`docs/cli/custom-commands.md`），**没有实机运行**；官方把子代理标为预览功能。

### Gemini 扩展
- **改动**：仓库根目录新增 `gemini-extension.json`（name `hq-orchestrator`，不设 `contextFileName`）和 `commands/hq.toml`、`commands/hq-retro.toml`（`/hq <目标>`、`/hq-retro`，提示模型用 `activate_skill` 激活对应技能，`{{args}}` 传目标）；扩展的技能直接用现有 `skills/`。扩展**不带**子代理：根目录 `agents/` 会被 Claude Code 插件当成自己的子代理加载，所以模板放在 `adapters/gemini/agents/` 由 install.sh 安装。`install.sh` 在 `--host gemini` 且已装扩展时提示重复（用户目录的技能优先于扩展）；卸载提示包含 Gemini 模板和扩展卸载命令。版本号在 install.sh、两个 Claude 清单和 Gemini 清单四处一致（有测试）。
- **原因/假设**：只用 Gemini CLI 的用户一条 `gemini extensions install` 就能装好，并有和 Claude Code 一致的 `/hq` 入口。
- **验收指标**：`tests/test_install.sh` 全部通过；用户反馈“扩展装不上 / `/hq` 激活不了技能”的问题数 = 0；Claude Code 插件里不出现 `commands/*.toml` 对应的命令。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### Gemini CLI 原生宿主
- **改动**：新增 `skills/hq/references/hosts/gemini.md`（子代理以同名工具 `hq-t0…t4` 调用、同步返回、不能续发消息；与主会话共用工作区，改代码任务先建 worktree；没有思考深度，只靠模型区分档位；用量填 null，W 通道可读；成本系数默认 low）。`adapters/render.sh` 新增 gemini 格式（`name`、`description`、`kind: local`、可选 `model`、`max_turns: 100`、`timeout_mins: 60`），生成 `adapters/gemini/agents/` 和 README；`agent-dirs.tsv` 加 `~/.gemini/agents`；`hosts.tsv` 中 gemini 改为 native。`SKILL.md` 加 gemini 识别，脚本查找路径加扩展目录；`runtimes.md`、`calibration.md`（Gemini 行、规则 9 成本系数）、`generic.md` 同步。`tests/test_install.sh` 增至 71 项。
- **原因/假设**：Gemini CLI 子代理可在定义文件里设 `model`，档位能逐任务生效，比降级模式快。
- **验收指标**：3c 按宿主/通道 → `gemini/A` 组有 ≥3 个任务时一次通过率 ≥ 70%；notes 含 `tier:not-applied` 的 gemini 任务占比 ≤ 20%；问题数里“子代理越界改主工作区” = 0。
- **状态**：待验证
- **复盘报告**：无（人工改动）

---

## v0.4.2（2026-11-25）

### W 通道后端化，新增 opencode、gemini、cursor
- **改动**：`skills/hq/scripts/cli-worker.sh` 拆成公共框架 + `scripts/backends/<cli>.sh`（`be_argv` 拼命令、`be_usage` 解析用量，接口见 `backends/README.md`）；codex、claude 行为不变。新增三个后端：opencode（`opencode run --model p/m#variant --format json`，简报走 stdin，`--effort` 追加为 variant，用量为 `step_finish` 的 input+output+reasoning+cache.write 逐步相加、cost 相加）、gemini（`gemini -m … --output-format stream-json --approval-mode … -p …`，简报走 stdin，用量取 `result.stats` 的 input_tokens−cached+output_tokens，不支持思考深度）、cursor（`cursor-agent -p --output-format stream-json --model … [--force] "<简报>"`，用量字段待核实）。后端可在建 worktree 前拒绝组合；映射有出入时写 `.hq/workers/<id>/notes` 并在 `start` 输出里返回。`--allow-dangerous` 闸门对所有 CLI 统一生效。`runtimes.md` W 节加各 CLI 映射表；`worker_clis` 可选值扩为五个，宿主自己的 CLI 不需授权；`generic.md` 让 Cursor、Gemini CLI 宿主经 W 用自己的 CLI 让档位生效；`opencode.md` 加 W 用法。假 CLI 加 opencode、gemini、cursor-agent；`tests/test_cli_worker.sh` 增至 53 项。
- **原因/假设**：Cursor、Gemini CLI 的原生子代理还不能按任务选模型，用它们自己的无界面命令做 worker 就能让档位生效；后端文件化后新增 CLI 只加一个文件。
- **依据**：opencode 来自 GitHub sst/opencode（2026-11-25）的 `run` 帮助夹具和 `run.rs`/`prompt.rs`；gemini 来自 google-gemini/gemini-cli 的 `docs/cli/headless.md`、`cli-reference.md` 和 `packages/core/src/output/types.ts`（2026-11-24）；cursor 来自官方参数页的检索摘要。**三者都未实机运行。**
- **验收指标**：`tests/test_cli_worker.sh` 全部通过；3c 按宿主/通道 → W 通道下 opencode/gemini/cursor 各组有 ≥3 个任务时一次通过率 ≥ 70%，`usage` 的 tokens 非 null 占比 ≥ 80%（cursor 除外，字段待核实）；问题数里“W worker 越界改主工作区” = 0。
- **状态**：待验证
- **复盘报告**：无（人工改动）

---

## v0.4.1（2026-11-25）

本版本把 OpenCode（V2）升级为原生宿主，并让子代理档位模板由一份档位表生成。OpenCode 部分**只读过官方文档源码（GitHub sst/opencode，2026-11-25），没有实机运行**。

### OpenCode 宿主适配
- **改动**：新增 `skills/hq/references/hosts/opencode.md`（5 节：`subagent` 工具按 `hq-t0…t4` 派发、后台运行并以 `<subagent>` 消息通知、带 `sessionID` 续发消息；stop_worker、worker_usage 待核实；子代理与主会话共用工作目录，改代码任务由主会话先建 `.hq/worktrees/<id>` 并在派发前后检查主工作区 `git status`；成本系数按 provider 判断）。`SKILL.md` 第 1 步加 opencode 识别（与 dsh 的 `subagent` 以参数区分）；`runtimes.md`、`calibration.md` 加 OpenCode 行；`generic.md` 移出 OpenCode；`hosts.tsv` 中 opencode 改为 native。
- **原因/假设**：OpenCode V2 的子代理可在 agent 文件里设 `model: provider/model#variant`，五档能逐任务生效，比降级模式快且省。
- **验收指标**：3c 按宿主/通道 → `opencode/A` 组有 ≥3 个任务时一次通过率 ≥ 70%；notes 含 `tier:not-applied` 的 opencode 任务占比 ≤ 20%；问题数里“子代理越界改主工作区”= 0。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### 子代理模板生成器与 `--with-agents`
- **改动**：新增 `adapters/tiers.tsv`（T0–T4 的思考深度、模型档次、适合任务）、`adapters/render.sh`（生成 codex TOML 和 OpenCode V2 Markdown，`--model-map` 填模型，`--check` 校验、`--all` 重新生成）、`adapters/agent-dirs.tsv`（模板安装目录）；`adapters/codex/agents/` 改为生成产物（内容只改了注释），新增 `adapters/opencode/agents/` 和 README。`install.sh` 新增 `--with-agents`（按所选宿主装模板）和 `--model-map`（只对一个宿主），保留 `--with-codex-agents`；卸载提示包含 OpenCode 模板目录。`tests/test_install.sh` 增至 64 项（生成结果与仓库一致、V2 格式、映射规则、非法映射、安装目录、多宿主、已存在不装一半、dry-run）。
- **原因/假设**：每加一个宿主就多 5 个手写模板，容易漂移；安装时直接填模型，避免用户手改占位符。
- **验收指标**：`tests/test_install.sh` 全部通过；用户反馈“模板模型未替换/格式错误”的问题数 = 0。
- **状态**：待验证
- **复盘报告**：无（人工改动）

---

## v0.4.0（2026-11-25）

本版本让 hq 能一键安装到更多代理工具（OpenCode、Cursor、Gemini CLI），并把安装逻辑改为登记表驱动。新工具只是**基础支持**（降级模式 + W 通道，档位不生效），目录来自官方文档检索，**未实机运行**。设计与后续路线见 `docs/design-more-hosts.md`。

### 宿主登记表 + install.sh 重写
- **改动**：新增 `adapters/hosts.tsv`（宿主、级别、专属目录、会读取的目录、检测命令/目录、下一步说明）和 `adapters/skill-dirs.tsv`（目录 key 与个人/项目路径）；`install.sh` 改为读登记表，`--host` 支持 `auto`（按命令或配置目录检测）、逗号列表、`all`（全部登记宿主）、`both`（兼容）；新增 `--layout minimal|per-host`（默认 minimal：贪心选能覆盖所选工具的最少目录，打平时优先单个工具的专属目录），`--list`、`--update`、`--uninstall`；每个副本写 `.hq-install.json`，个人范围写 `~/.hq/skill-path`；不在仓库内运行时（`curl | bash`）先用 git 下载 `v<版本>` 标签（`HQ_REF`、`HQ_REPO_URL`、`HQ_CACHE_DIR` 可覆盖）到 `~/.hq-orchestrator/`。新增退出码 4（没有可操作的对象）、5（下载失败）。保持 bash 3.2 兼容、只复制文件、先检查后写入。
- **行为变化**：`--host all` 从“claude、codex、dsh 三处”改为“全部登记宿主 + 最小集合”，即只装 `~/.agents/skills` 和 `~/.claude/skills`；要旧行为用 `--layout per-host`。
- **原因/假设**：多数工具已共用 `.agents/skills`、`.claude/skills`，分发不难，难在别重复装、别让用户自己查目录；登记表让新增宿主只需加一行。
- **验收指标**：`tests/test_install.sh` 全部通过（48 项，含新宿主、最小集合、auto、list/update/uninstall、引导下载、登记表自洽）；用户反馈的安装问题数 = 0；在 OpenCode、Cursor、Gemini CLI 各实测一次能发现并触发 hq 技能。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### 通用宿主文档与技能内的路径
- **改动**：新增 `skills/hq/references/hosts/generic.md`（OpenCode/Cursor/Gemini CLI/其他的识别表、能力表、档位记录方式 `tier:not-applied`、待核实项）；`SKILL.md` 第 1 步识别 opencode/cursor/gemini/other 并指向 generic.md，脚本查找先读 `~/.hq/skill-path` 再 find（路径加入 opencode/cursor/gemini 目录）；`hq-retro/SKILL.md` 同步；`metrics-schema.md` 的 host 取值加 `opencode`/`cursor`/`gemini`；`runtimes.md` 宿主索引更新；README 中英文更新安装说明并加入 `npx skills add`。
- **原因/假设**：装到新工具后，技能要能找到自己的脚本，并按统一方式记录 host，复盘才能按宿主比较。
- **验收指标**：3c 按宿主/通道 → opencode/cursor/gemini 的任务 host 字段都有值；缺记录任务数 = 0。
- **状态**：待验证
- **复盘报告**：无（人工改动）

---

## v0.3.2（2026-11-25）

### 低成本宿主拿不准时上调一档
- **改动**：`calibration.md` 新增规则 9：按实际计费方设成本系数（Claude Code 为 high；Codex、dsh、DeepSeek 后端为 low），low 宿主拿不准难度时（离上一档 ≤1 分、模糊度 ≥1，或在两档间犹豫）上调一档，最多一档；关键路径上的小任务或遇到限流时不上调；上调的任务在 notes 记 `bias:+1(cost_low)`。`playbook-template.md` 授权区新增 `cost_weight`；`hosts/codex.md`、`dsh.md`、`deepseek.md` 第 3 节引用此规则；README 中英同步。
- **原因/假设**：用户偏好。Codex 和 DeepSeek 的额度比 Claude 耐用，选高的边际成本低，用低档失败重来的代价相对更高；上调一档能提高一次通过率，而用时增加可以接受。
- **验收指标**：low 宿主上 notes 含 `bias:+1(cost_low)` 的任务 ≥5 个后，其一次通过率不低于同宿主未上调的任务，且 actual/est 中位数不高于后者的 1.5 倍；否则收回或缩小适用范围。
- **状态**：待验证
- **复盘报告**：无（用户偏好，人工改动）

## v0.3.1（2026-11-25）

本版本把 DeepSeek Harness（dsh）作为第三个原生宿主接入，DeepSeek 的推荐路径改为 dsh。dsh 部分**只读过官方仓库 deepseek-ai/deepseek-harness 提交 4b399c3 的文档，没有实机运行**，验证清单见 README“待核实项与本机验证清单”。

### dsh 宿主适配
- **改动**：新增 `skills/hq/references/hosts/dsh.md`（5 节、9 项能力：`subagent` 逐次传 provider/model/reasoning_effort，首次先 `list_subagent_models`；完成通知 + `list_agents` 监控；`send_message`；Schedule 做 schedule_checkin；stop_worker、worker_usage 待核实；外部后端不能选模型；并发取子代理树容量与 resources.sh 槽位较小值；W 通道暂不接入）。`hosts/deepseek.md` 改为三条路径，路径一（推荐）为 dsh，原两条顺延为路径二、三。`SKILL.md` 第 1 步加 dsh 识别特征，`SKILL.md` 与 `hq-retro/SKILL.md` 的 find 路径加 `~/.dsh/skills`、`.dsh/skills`。`calibration.md` 加 dsh 映射行（T0–T2 flash low/low/medium，T3–T4 pro medium/high），`runtimes.md` 宿主索引、`metrics-schema.md` host 取值加 `dsh`。
- **原因/假设**：dsh 每次派子代理都能指定模型和思考深度，五个档位能逐任务生效，比经 Claude Code（`CLAUDE_CODE_EFFORT_LEVEL`/`CLAUDE_CODE_SUBAGENT_MODEL` 可能覆盖档位、B 通道走 Claude 模型）或 Codex 接入更直接。
- **验收指标**：3c 按宿主/通道 → `dsh/A` 组有 ≥3 个任务时一次通过率 ≥ 70%；3a 按档位 → dsh 宿主下 T3/T4 一次通过率不低于 T0–T2；PLAYBOOK 有 dsh 映射行；缺记录任务数 = 0。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### install.sh：`--host dsh` 与 `--host all`
- **改动**：`install.sh` 的 `--host` 新增 `dsh`（个人范围 `${DSH_HOME:-~/.dsh}/skills`，项目范围 `<项目>/.dsh/skills`）和 `all`（三处都装）；`both` 保留作兼容（claude + codex）。usage 说明 dsh 也读 `~/.agents/skills`，装过 codex 不必重复装。`tests/test_install.sh` 补 dsh 个人/项目范围、`DSH_HOME`、`all`、`both` 兼容和 usage 说明的用例。
- **原因/假设**：让 dsh 用户一条命令装好；`all` 覆盖三种宿主，`both` 不破坏旧脚本。
- **验收指标**：`tests/test_install.sh` 全部通过；用户反馈的安装问题数 = 0。
- **状态**：待验证
- **复盘报告**：无（人工改动）

---

## v0.3.0（2026-11-25）

本版本让插件宿主无关：能在 Claude Code、Codex 上运行，并能通过这两者接入 DeepSeek 后端；其他工具走 W 通道或降级模式。Codex 和 DeepSeek 部分**都没有实机运行过**，验证清单见 README“待核实项与本机验证清单”。验收指标都能从 `metrics.py` 报告直接读出（“小节名 → 列名”），新增“3c. 按宿主/通道”小节。

### SKILL.md 宿主无关化与宿主文档
- **改动**：`skills/hq/SKILL.md` 只用抽象能力（spawn_worker、monitor、message_worker、stop_worker、worker_usage、schedule_checkin、remote_workers、local_machine、concurrency_limit）；第 1 步按特征识别宿主；具体调用移到 `references/hosts/{claude-code,codex,deepseek}.md`，`runtimes.md` 改为能力和通道总览。
- **原因/假设**：同一套流程能跑在多个宿主上，宿主差异集中在宿主文档里维护，SKILL.md 不再随某个宿主的工具名变化。
- **验收指标**：3c 按宿主/通道 → 每个有 ≥3 个任务的宿主组，一次通过率 ≥ 70%；质量门槛 → Claude Code 宿主的漂移率不高于 v0.2 同类运行；缺记录任务数 = 0。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### 抽象档位 + 宿主映射
- **改动**：`skills/hq/calibration.md` 档位改为与宿主无关的 T0–T4“所需能力”，另列各宿主映射；首次在新宿主上运行时把实际映射写进 PLAYBOOK“选档偏好”。数值和修正规则不变。
- **原因/假设**：不同宿主模型名不同，但难度分档逻辑相同；按宿主分开记录，复盘才能比较。
- **验收指标**：3a 按档位 → 各档一次通过率 ≥ 80%（与 v0.2 相同阈值，不因换宿主下降）；PLAYBOOK 中每个用过的宿主都有映射行。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### W 通道：CLI 子进程 worker（含 sandbox 闸门）
- **改动**：新增 `skills/hq/scripts/cli-worker.sh`（start/status/stop/usage/list），在 `.hq/worktrees/<id>` 里后台运行 `codex exec` 或 `claude -p`。sandbox 默认 `workspace-write`；`danger-full-access`（claude 为 `--dangerously-skip-permissions`）必须同时传 `--allow-dangerous`，否则退出码 2。codex 用量按 `turn.completed.usage` 计算：input 扣除 cached，output 已含 reasoning 不重复加，usage 为线程累计值。跨厂商 worker 须在 PLAYBOOK 授权区开启 `worker_clis`，默认关闭。测试 `tests/test_cli_worker.sh`（假 CLI）。
- **原因/假设**：没有子代理能力的宿主也能并行；需要真正的进程隔离时有选择；高风险权限不能因一个参数或默认值被打开。
- **验收指标**：3c 按宿主/通道 → `*/W` 组一次通过率 ≥ 70%、tokens 为 null 的比例 ≤ 20%；W 任务的漂移率 ≤ 10%。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### Codex 适配模板
- **改动**：新增 `adapters/codex/agents/hq-t0…hq-t4.toml` 和说明。字段（必填 name/description/developer_instructions，可选 model/model_reasoning_effort）和目录（`~/.codex/agents/`、`<项目>/.codex/agents/`）已按官方文档核对（2026-11-25），未实机运行；模型名是占位符。
- **原因/假设**：Codex 原生子代理按档位选 agent，比 W 通道开销小、能并行。
- **验收指标**：3c 按宿主/通道 → `codex/*` 组一次通过率 ≥ 70%；复盘时 codex 宿主的 PLAYBOOK 有完整 T0–T4 映射。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### DeepSeek 后端两条接入路径
- **改动**：新增 `references/hosts/deepseek.md`：路径一 Claude Code 接 DeepSeek（档位合成 flash/pro 两档，不设 `CLAUDE_CODE_SUBAGENT_MODEL`），路径二 Codex 接 DeepSeek。标注风险：官方建议的 `CLAUDE_CODE_EFFORT_LEVEL=max` 可能覆盖按档位设置的 effort（未下结论），`claude-code.md`、`calibration.md` 同步标注，task notes 记 `effort_env:max`；cost_usd 不可信，notes 记 `billing:deepseek`。
- **原因/假设**：用户想用更便宜的后端；flash/pro 两档加思考深度能覆盖 T0–T4。
- **验收指标**：DeepSeek 后端的 T3/T4 任务一次通过率 ≥ 70%（3a 按档位，按 notes 过滤）；带 `effort_env:max` 与不带的同档任务，平均 tokens 差异在复盘中有结论。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### 降级模式
- **改动**：`SKILL.md` 第 1 步：宿主没有子代理能力也用不了 W 时，主会话按同样的计划、台账、质量门槛串行亲自执行，channel 记 `main`；此时暂停铁律 1（不做重活），其余铁律照常。`PROMPT.md` 同步。
- **原因/假设**：在 OpenCode、Gemini CLI、Cursor 等工具里也能用同一套流程和数据记录。
- **验收指标**：3c 按宿主/通道 → `*/main` 组漂移率 ≤ 10%、缺记录任务数 = 0。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### install.sh
- **改动**：新增 `install.sh --host claude|codex|both [--scope user|project] [--with-codex-agents] [--force] [--dry-run]`：技能装到 `.claude/skills` 或 `.agents/skills`；agent 模板个人范围装到 `~/.codex/agents`，项目范围装到 `<项目>/.codex/agents`。先检查全部目标（含 agent 模板），已存在退出码 3，不装一半；不改任何配置。测试 `tests/test_install.sh`。
- **原因/假设**：多宿主的安装位置不同，手工复制容易放错。
- **验收指标**：用户反馈的安装问题数 = 0（复盘看 user_corrections 备注）；`tests/test_install.sh` 全部通过。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### 运行数据增加宿主维度
- **改动**：`metrics-schema.md` 的 task/run 增加可选字段 `host`；跨厂商 model 写成 `<cli>:<模型名>`；`metrics.py` 报告新增“3c. 按宿主/通道”；`/hq-retro` 复盘清单第 9 项做跨宿主、跨厂商对比（每组 ≥3 个任务才比较）。
- **原因/假设**：没有宿主维度就无法判断哪个宿主、哪条通道更划算。
- **验收指标**：3c 按宿主/通道 → `unknown/*` 组任务占比 ≤ 10%（新运行都应填 host）。
- **状态**：待验证
- **复盘报告**：无（人工改动）

## v0.2.0（2026-11-24）

本版本是一次整体升级，下面每条都是假设，还没有数据。v0.1 没有运行数据，所以验收指标都写成绝对阈值，不和 v0.1 比；所有指标都能从 `metrics.py` 报告直接读出（“小节名 → 列名”）。

### 要不要编排的判断
- **改动**：`skills/hq/SKILL.md` 新增“第 0 步：要不要编排”：预计不到约 30 分钟或高度耦合的工作不编排，直接在当前会话做。
- **原因/假设**：编排有固定成本（实测一个小子代理约 7.3 万 token 花在熟悉项目上），小任务开子会话得不偿失。
- **验收指标**：效率 → 任务数 ≤ 2 的 run 占比 ≤ 20%（这类 run 本应不编排）；自主性 → user_corrections 每任务 ≤ 0.1。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### 并行以总用时为准、小任务打包、难度单一
- **改动**：`skills/hq/SKILL.md` 第 2 步：以缩短关键路径为目标而不是并行数最多；小而相关的任务打包给一个子会话，约 15 分钟以上且文件不重叠才拆开；每个任务内部难度一致。
- **原因/假设**：每开一个会话都有启动成本；打包后总用时和成本都会下降，难度单一能减少中途调档。
- **验收指标**：效率 → 并行加速比 ≥ 1.3 且 wall/关键路径 ≤ 1.5；按档位 → 各档一次通过率 ≥ 80%；调档与检查点 → 升档任务数 / 总任务数 ≤ 15%。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### 按风险分级验证
- **改动**：`skills/hq/SKILL.md` 第 8 步“验证分级”（doc / code / high / e2e）和 `references/brief-template.md` 的“验证”节：子会话只做本级该做的验证，只有 high 级主会话才逐个复跑验收命令，全量测试在归并后统一跑一次。
- **原因/假设**：减少多余验证，同时不放过高风险任务的问题。
- **验收指标**：质量门槛 → 验证到位率 ≥ 90%、合并通过率 ≥ 90%、integration 问题/任务 ≤ 0.2（少验证的代价会先在合并环节暴露）。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### 选档移入 calibration.md，并算上失败重来的成本
- **改动**：打分表、档位表和修正规则从 `skills/hq/SKILL.md` 移到 `skills/hq/calibration.md`；新增规则 1（算上失败重来的成本）、规则 2（看不准先调研）、规则 6（不降档交接）。
- **原因/假设**：低档失败重来的总成本可能高于一次选对高档；复盘只调一个文件。
- **验收指标**：按档位 → 各档一次通过率 ≥ 80%、升档率 ≤ 15%；质量门槛 → 返工率 ≤ 10%。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### 动态调档与检查点
- **改动**：`skills/hq/SKILL.md` 第 7 步“动态调档”、`references/brief-template.md`“遇到问题时”、`references/runtimes.md`“建议用户手动调档”：子会话在超范围衍生、难度超预期、同一问题失败 2 次时发 CHECKPOINT；卡住时升一档新开会话从分支接着做；不做降档交接。
- **原因/假设**：尽早发现选档错误，减少整任务失败后重来。
- **验收指标**：调档与检查点 → 升档任务中有检查点的比例 ≥ 50%（近似“升档发生在检查点，而不是等失败之后”）；质量门槛 → 漂移率 ≤ 10%。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### 三项质量门槛
- **改动**：`skills/hq/SKILL.md` 第 8 步：把“不漂移、验证到位、问题少”定为质量门槛，审核和复盘（`skills/hq-retro/SKILL.md`）都以此为准；用时归入效率指标。
- **原因/假设**：用统一标准判断质量，优先于比时间和成本。
- **验收指标**：metrics 能稳定算出漂移率、验证到位率、各环节问题数（总览 → 缺记录任务数为 0 或 `-`，损坏行数为 0）；质量门槛 → 漂移率 ≤ 10%。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### 记录数据与复盘
- **改动**：`skills/hq/SKILL.md` 第 9 步：每个任务、每次运行往 `.hq/runs/<run_id>.jsonl` 追加记录；新增 `references/metrics-schema.md`（格式 v1，含用量口径：`cost_usd` 为主要成本指标，`tokens` 不含缓存读取）、`scripts/metrics.py`（只读汇总，同一任务重复记录只算一次）、`/hq-retro` 技能、`references/playbook-template.md`、本文件。
- **原因/假设**：用数据而不是印象改进插件，改动可追溯、可验证、可撤回。
- **验收指标**：总览 → 缺记录任务数 / 任务数 ≤ 5%、损坏行数为 0；连续 2 次复盘能从数据中得出至少 1 条通过证据门槛的结论或明确的“无建议”（看 `.hq/retro/` 报告）。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### 自主决策与停止条件
- **改动**：`skills/hq/SKILL.md` 铁律 2 和“自主决策与停止条件”：计划只通知不等确认，只有 3 类情况停下找用户，问题攒齐一次问；授权写在 PLAYBOOK“授权”区（`merge_default`、`open_pr`、`budget_usd`、`autonomy`）。
- **原因/假设**：减少不必要的打断，同时保证越权的事一定停下来。
- **验收指标**：自主性 → autonomy_stops / run 数 ≤ 1、user_corrections 每任务 ≤ 0.1；质量门槛 → major 数为 0（越权操作会表现为用户反馈的严重问题，原因写进 notes）。
- **状态**：待验证
- **复盘报告**：无（人工改动）

---

## v0.1.x（复盘后的小改进）

这三条来自 v0.1.0 实际运行后的人工复盘。当时还没有运行数据记录，所以只能等 v0.2 的数据来验证，状态都是“待验证”。

### 派 worktree 任务前检查忽略规则
- **改动**：`skills/hq/SKILL.md` 第 5 步（v0.2 起为第 6 步“派发”）：派 worktree 任务前确认 `.claude/worktrees/` 被 git 忽略，否则写入 `.git/info/exclude`；合并后清理 worktree 和临时分支。
- **原因/假设**：未被忽略时，子代理的临时目录显示为未跟踪文件，可能触发 hook 或被误提交。
- **验收指标**：之后的运行里，`notes` 写明由 worktree 目录未跟踪导致的问题数为 0（metrics 不单独统计，复盘时检索 notes）。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### 巡检间隔按预计时长设定
- **改动**：`skills/hq/SKILL.md` 第 6 步（v0.2 起为第 7 步“监控”）：巡检间隔取预计时长的 1 到 1.5 倍，最短 3 分钟，最长 30 分钟。
- **原因/假设**：固定间隔对小任务太长、对大任务太密，会空转或拖慢收尾。
- **验收指标**：效率 → wall/关键路径 ≤ 1.5（巡检太稀会拖慢收尾、拉高这个比值）。巡检次数本身不记录，太密的代价只体现在主会话消耗上，暂不量化。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### 云端删除远程分支可能失败时交给用户
- **改动**：`skills/hq/SKILL.md` 第 7 步（v0.2 起为第 8 步“审核与归并”第 5 项）：云端 Git 通道删除远程分支失败时，试一次就停，把分支列在最终汇报里交给用户。
- **原因/假设**：云端通道可能不允许删分支，反复重试和绕路只会浪费时间。
- **验收指标**：行为规则，无量化指标。之后的运行里，`notes` 写明由反复重试删分支造成的问题数为 0（复盘时检索 notes）。
- **状态**：待验证
- **复盘报告**：无（人工改动）

---

## v0.1.0（初版）

### 司令部模式初版
- **改动**：新增 `/hq` 技能（`skills/hq/SKILL.md`）、`references/brief-template.md`、`references/runtimes.md`、`scripts/resources.sh`、中英文 README。
- **原因/假设**：由主会话统筹规划，按难度给子会话选模型和思考深度，按系统资源控制并发，审核后归并。
- **验收指标**：初版，无量化指标。由 v0.2 的数据记录接手评估。
- **状态**：已验证（能完成真实的多任务编排运行；`tests/test_resources.sh` 通过）
- **复盘报告**：无
