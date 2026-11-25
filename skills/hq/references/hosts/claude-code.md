# 宿主适配：Claude Code

`SKILL.md` 只引用抽象能力（spawn_worker、monitor 等）。本文件写这些能力在 Claude Code 里的具体做法。通道的通用规则见 `../runtimes.md`。

## 1 概述与适用版本

- 适用：Claude Code CLI（本地终端）、Claude Code 云端会话（claude.ai/code）、桌面端和 IDE 扩展里的 Claude Code。
- 识别特征：有 `Agent` 工具，或者有 `mcp__claude-code-remote__*` 工具。云端会话的系统提示里有 remote execution environment。
- 接 DeepSeek 后端的 Claude Code（`ANTHROPIC_BASE_URL` 指向 deepseek）：工具面相同，但模型名、计费和部分能力不同，以 `deepseek.md` 为准，本文件只作工具调用参考。
- 核实日期：2026-11-25；来源：本插件 v0.2 在 Claude Code 云端会话中的实际使用记录（`runtimes.md` v0.2 内容）和当前会话可见的工具定义。`claude` CLI 发起云端任务的参数（通道 D）待核实。

## 2 能力表

| 能力 | 怎么做 | 不支持时的降级 |
|---|---|---|
| spawn_worker | A：`Agent(description, subagent_type="general-purpose"（只读调研用 "Explore"）, model, effort, isolation="worktree"（改代码必加）, run_in_background=True, prompt=<说明>)`。B：`mcp__claude-code-remote__create_session(title, prompt, source_url, source_revision, outcome_branch="hq/<id>", model, effort, tags=["hq:<项目>"])`，不要传 `permission_mode="plan"`。W：`bash <cli-worker.sh> start --id <id> --cli claude\|codex --model <m> [--effort <e>] --brief <文件>` | 没有 Agent 也没有 B：用 W；没有 shell：降级模式（主会话串行亲自做，channel 记 `main`） |
| monitor | A：后台子代理完成自动通知，不要轮询；`TaskList` 看正在运行的。B：`list_sessions(children=true)` 看全局，`get_session(id)` 看 `status_bucket`（working / blocked / review_ready / completed / failed），`list_events(session_id, kinds=["result","assistant"], limit=100)` 看结果。W：`cli-worker.sh status --id <id>` / `list` | 等分支推送后 `git fetch` 审核 |
| message_worker | A：`SendMessage` 发给子代理 id。B：`send_message(session_id, ...)`，子会话创建后、运行中、空闲或阻塞时都能发（实测返回 `delivered`，消息以 `<cross-session-message from-session=…>` 的形式排进对方队列）；`priority` 取 `now`（打断当前轮）、`next`（并入运行中的轮）、`later`（等本轮结束）。子会话回报主会话也用它，说明里写上主会话 session_id（`get_session()` 不带参数可查自己的 id），或让子会话用 `@parent`。**auto 模式下子会话的 `send_message` 会卡在人工批准上，见 §5。** W：无回信通道 | 没有回信通道：worker 提前返回或写在交付格式里，主会话通过 monitor 读取 |
| stop_worker | A：`TaskStop`。B：`interrupt_session`，收尾用 `archive_session`。W：`cli-worker.sh stop --id <id>` | 请用户手动停止 |
| worker_usage | B：`get_session(id).usage`：`cost_usd` 直接用；tokens = input + output + cache_write，不加 cache_read。B 的 `actual_min`：从 `created_at` 到交付那一轮结束（`external_metadata.turn.ended_at`，毫秒时间戳）的分钟数，不含之后等审核、合并的时间。A：返回结果的 duration 写 `actual_min`；`subagent_tokens` 分不出缓存读取时 tokens 填 null，原值记进 notes。W：`cli-worker.sh usage --id <id>`（JSON） | 拿不到填 null，不估算 |
| schedule_checkin | B 场景：`send_later(delay_minutes=N, message="HQ 巡检：读取 .hq/LEDGER.md，检查 RUNNING 任务")`；回报到达或任务全部完成后 `delete_trigger` 取消未触发的提醒 | A 自动通知，不需要；本地 CLI 无定时能力时在每次主会话回合检查 |
| remote_workers | 云端会话：B（`mcp__claude-code-remote__*`），默认继承主会话云环境；需要其他网络或密钥时用 `list_environments` 查 `environment_id` 再传入。本地 CLI：D（先查 `claude --help` 有无创建云端会话的参数，如 `--remote`/`--cloud`，待核实） | 只用 A 或 W |
| local_machine | 主会话在本地：直接执行。主会话在云端：C，`list_computer_folders`（只选 `online:true`）→ `request_computer_folder(environment_id, computer_name, folder)`（用户批准）→ 之后 Bash/Read/Edit 等工具带 `_host:"<电脑名>"`；一次只能连一台电脑的一个文件夹 | 连不上就标 BLOCKED，其余照常 |
| concurrency_limit | B：默认远程并发 ≤4（预算项）。A、C、W：按 `resources.sh` 的本地槽位 | 串行 |

## 3 档位映射

| 档位 | 模型 | 思考深度（effort） |
|---|---|---|
| T0 | haiku | low |
| T1 | sonnet | low |
| T2 | sonnet | medium |
| T3 | opus | medium |
| T4 | opus | high（必要时 xhigh） |

`max` 只在用户明确要求时使用。W 通道跑 `claude -p` 时用同样映射（sandbox 默认 workspace-write → `--permission-mode acceptEdits`；`danger-full-access` 必须另加 `--allow-dangerous`）；跑 `codex exec` 时见 `codex.md`，model 记为 `codex:<模型名>`。

## 4 安装与调用

- **插件**：在 Claude Code 里添加本仓库为插件市场后安装（`/plugin marketplace add lostoy0/hq-orchestrator`，再 `/plugin install`），技能位于插件目录的 `skills/hq/`。
- **个人技能**：把 `skills/hq`、`skills/hq-retro` 拷到 `~/.claude/skills/`（项目级放 `.claude/skills/`）。
- 调用：输入 `/hq <目标>` 或说“司令部模式”；复盘用 `/hq-retro`。
- 找脚本：`find ~/.claude/skills ~/.claude/plugins .claude/skills -path '*hq/scripts/resources.sh' 2>/dev/null | head -1`。

### 通道细节

- **A**：子代理和主会话同机，派发前必须过 `resources.sh`。worktree 需要 git 仓库，否则写操作只能串行。派 worktree 任务前确认 `.claude/worktrees/` 已被忽略（`git check-ignore -q .claude/worktrees/x`），没有就写进 `.git/info/exclude`。检查点：子代理没有回信通道，提前返回。
- **B**：子会话只能看到已推送的代码；基线没推送就推到 `hq/base` 等 `hq/*` 分支。说明里写上主会话 session_id。
- **C**：资源检测也要在那台电脑上跑：`Bash(_host=..., command="bash <路径>/resources.sh 1500 1")`，脚本需先拷过去或内联。子代理用不了 `_host` 时由主会话亲自执行这些本地步骤。
- **D**：主会话难以自动监控；需要强监控时建议把整个编排放到云端会话做（B + C）。
- **W**：见 `../runtimes.md` 的 W 节；Claude Code 里通过 Bash 工具调用 `cli-worker.sh`。

### 建议用户手动调档（话术）

> 任务 t3（会话 session_01AbC…，标题“hq/t3 导出接口”）在同一个并发问题上已失败 2 次，它已积累大量上下文，换会话交接代价高。建议：在 claude.ai/code 打开这个会话，把模型切到 opus；如果界面提供思考深度选项，调到 high（运行中的会话能不能改深度取决于界面是否提供该选项）。切好后回复“已切换”，我会让它继续。不方便切换的话回复“交接”，我改为用 opus 新开会话从 hq/t3 接着做。

## 5 已知限制与待核实项

- 云端会话里 Git 通道可能不允许删除远程分支（`unexpected disconnect` / `remote end hung up`），试一次就停，列进汇报交给用户。
- B 子会话正常完成不一定通知主会话（主会话只在子会话的轮次失败或 worker 重启时收到 `<child-session-event>`），必须靠回报加 schedule_checkin 兜底。
- **auto 模式下子会话主动汇报不可用（2026-11-25 实测，haiku 子会话，权限模式继承 auto）**：
  - 子会话调 `send_message` 发给主会话，会停在 `REQUIRES_ACTION`（“This connector call requires your approval to proceed”），请求带 `suppress_always_allow_rule:true`，不能点“总是允许”；无人批准就一直卡住，主会话收不到任何消息。
  - 子会话发给兄弟会话的 `send_message` 被 auto 模式分类器拒绝，原因标为 “Unsanctioned Communication”。
  - 仓库 `.claude/settings.json` 里写 allow 规则 `mcp__claude-code-remote__send_message`、子会话带 `source_url` 检出该分支后，仍然出现同样的批准请求，没有生效。
  - 用 `create_session` 的 `extra_allowed_tools` 预批准 `send_message`，被分类器拒绝（“Undermining Oversight”）。
  - 卡在批准上的子会话在 `get_session` 里是 `status_bucket=blocked`，`post_turn_summary.status_category=need_input`、`needs_action` 写着要批准的工具，巡检时可据此识别。
  - 因此无人值守时，不要把“子会话会主动回报”当作前提：说明里同时要求把结果写进交付文件（分支或 `.hq/`），主会话靠 monitor 读取。用户在场、愿意逐条批准时，回报可用。
  - 主会话发给子会话的 `send_message` 不受影响。
- 兄弟会话之间能否直连、手动批准后后续消息是否还要重复批准：未验证。
- 运行中的子会话改不了模型和思考深度。
- A 的 `subagent_tokens` 不分缓存读取，tokens 常为 null。
- 接 DeepSeek 后端时的模型名、档位映射、用量口径：见 `deepseek.md`。
- **effort 风险（未下结论）**：DeepSeek 官方建议设 `CLAUDE_CODE_EFFORT_LEVEL=max`，它可能覆盖 hq 按档位传的 effort（A 通道的 `effort` 参数、W 通道的 `--effort`），使上表的思考深度列不生效，T0–T2 成本上升。是否覆盖待实测；设了该变量时，task 记录 notes 标注 `effort_env:max`，复盘时按此分组。
- 待核实：D 通道 CLI 参数名；插件市场安装命令在各版本中的写法。
