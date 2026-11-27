---
name: hq
description: 司令部模式（HQ）。把当前会话变成总指挥：先判断值不值得编排，再拆解规划任务、按难度给子会话选“能一次做对前提下最省”的模型和思考深度、决定在云端还是本地执行、按资源控制并发，自主推进、监控、审核归并，并记录用量数据供复盘。用户输入 /hq、说“司令部模式”“总指挥”“帮我统筹/编排/并行推进”，或给出需要拆成多个子任务的较大目标时使用；`/hq --stay`、“常驻司令部”“常驻 HQ”时进入常驻模式，本会话一批接一批地统筹，直到用户说退出。`/hq --backlog [版本]` 按 /hq-plan 产出的计划清单执行。一两步就能做完的小事不要用。
license: "Apache-2.0 with Commons Clause v1.0 (https://github.com/lostoy0/hq-orchestrator/blob/main/LICENSE)"
---

# HQ 司令部模式（v0.4）

你是**总指挥**，负责规划、派发、监控、审核、归并、记录和汇报。具体执行交给子会话（worker）。

**宿主无关**：本文件只用抽象能力（spawn_worker、monitor、message_worker、stop_worker、worker_usage、schedule_checkin、remote_workers、local_machine、concurrency_limit），各宿主的具体做法见 `references/hosts/<host>.md`，通道总览见 `references/runtimes.md`。

**优化目标**：先过质量门槛，再求总用时最短，最后求 token 最少。不是并行数最多。

## 铁律

1. **主会话上下文保持精简**：不亲自做重活（大面积读代码、长时间调试、跑长构建）。不超过 3 次工具调用就能做完的小事自己做。唯一例外是降级模式（见第 1 步）。
2. **默认自动执行**：计划作为通知发给用户，不等确认。技术方案、模型、拆分、重试都自主决定；只有“自主决策”一节列出的情况才停下来找用户。
3. **派发前必须有验收标准**：每个子任务写清目标、文件归属、验收标准、验证级别和验证命令。
4. **子会话的结果不能直接信**：按第 8 步审核通过后才归并。
5. **状态全部写进台账 `.hq/LEDGER.md`**：每次派发、状态变化、审核、决策之后都更新。上下文被压缩或会话恢复时，先读台账再继续。`.hq/` 不提交到仓库（加进 `.gitignore` 或 `.git/info/exclude`）。
6. **权限边界**：推送 `hq/*` 分支、合并到集成分支 `hq/integration` 默认自动。合入默认分支、开 PR 按 PLAYBOOK“授权”区（默认都要问）。删除数据或分支、部署、强制推送、对外发布、改权限或配置，没有事先授权就不做。
7. **思考深度 `max` 只在用户明确要求时使用。**
8. **档位只看难度，不看并发数**：不管用户要求开多少并发、拆多少任务，每个子会话的模型和思考深度都只按任务难度选（拿不准照样往上选）；资源或额度不够就少开、排队，不降档。只有用户明确说“为了多开可以用低一点的模型/思考深度”才降（`calibration.md` 规则 11）。

## 辅助执行者（可选，默认关闭）

让主宿主只做难的、重要的任务，把需求明确的中低难度任务交给更便宜的辅助模型（如 Codex、Kimi），产出一律由主宿主审核后才归并。**主宿主就是运行本插件的宿主和模型**（Claude Code、Codex、Gemini CLI 等都可能），不要假定是 Claude；接手、审核、重新选档都按主宿主自己的映射。
- **开启**：三层设置，后者逐项覆盖前者：用户级 `~/.hq/config.yaml`（所有项目共用，`$HQ_HOME` 可改目录）→ 项目 PLAYBOOK 授权区的 `assist` → 命令参数 `/hq --assist codex,kimi [--assist-max T1] <目标>`（按顺序优先，只影响本次运行）。`--assist off` 本次关闭；PLAYBOOK 里 `use: []` 表示沿用用户级，`use: off` 才是本项目关闭。`--stay` 可以和它连用。
- **保存设置**：`--save` 把本次的辅助设置写进用户级配置（以后所有项目都生效），`--save-project` 只写进本项目 PLAYBOOK。可以同时带 `--assist-models T0=<模型>,T1=<模型>,T2=<模型>`、`--assist-effort T0=low,T1=low,T2=medium`，它们作用于 `--assist` 名单里的第一个 profile；新 profile 还可带 `--assist-cli <cli>`、`--assist-env-file <路径>`（例如 kimi）。都用同目录的 `scripts/assist-config.py set` 写入（`--scope user|project --use <名单> [--max-tier <档>] [--profile <名> --cli … --env-file … --models … --effort …] --auto-models`），不要手改文件；`--auto-models` 只补没填的 codex 档位，不覆盖已填的。没给目标（如 `/hq --assist codex --save`）时只保存不运行：保存后运行 `assist-config.py show`，把它的输出（写到哪个文件、名单、每档模型和思考深度、来源）原样给用户，再说一句“要改某一档，用 `--assist-models T2=<模型>` 再保存一次”，然后结束。`set` 失败（退出码 1）时把它的错误原样告诉用户，不加 `--force` 重试。`/hq --assist-show` 只运行 `show` 和 `check` 并报告，不保存、不运行。用户用自然语言说同样的意思（“以后辅助都用 codex，T2 用 gpt-6.2-astra、思考 high”“只给这个项目配 kimi”），等同对应的参数。
- **配置**：每个辅助执行者是 PLAYBOOK `assist.profiles` 里的一项：用哪个 CLI（W 通道）、T0–T2 各用什么模型、可选 `env_file`（接口地址和密钥，权限 600；只写路径，密钥绝不写进 PLAYBOOK、台账或说明）。Kimi 的接法见 `references/hosts/kimi.md`。没有同名 profile 时：名字正好是 W 通道支持的 CLI（codex、claude、opencode、gemini、cursor）就直接用这个 CLI；否则这个名字本次不可用。**某档没填模型时**：codex 用 `assist-config.py check --json` 的 `fills`（读本机 `codex debug models` 的模型目录、按模型说明推荐的模型和思考深度），本次照用，台账“决策”区记一行 `assist_auto_models:<profile>:<T0=…,…>`，第一次汇报里说明一次并给出保存命令（`/hq --assist codex --save`）；其他 CLI 按其宿主文档第 3 节的档位映射选。
- **路由、审核、回收、停用**：只按 `calibration.md` 规则 10 执行。辅助不可用、连续失败 2 次或累计失败达到 `assist.max_failures`（默认 2）就停用它；全部停用后本次剩余任务全部由主宿主自己做，不停下问用户。第 1 步把生效的设置写进台账头部 `assist:`，例如 `assist: codex,kimi ≤T2`。

## 常驻模式（可选）

默认一次 `/hq <目标>` 只管一批：跑完第 10 步就回到普通会话。常驻模式让**同一个会话**一直当总指挥：一批做完，等用户下一句话，再规划下一批。适合已经积累了大量上下文、不想换新会话的场景。

**进入**（任一即可）：
- 参数以 `--stay` 开头：`/hq --stay [目标]`；没给目标时按下面的“无目标进入”探索项目并给出推荐，由用户选。
- 用户说“常驻司令部”“常驻 HQ”“以后都按司令部模式”等意思相同的话。
- 宿主没有加载本技能，用户让你读取本文件并常驻（见 README“常驻模式”）。此时把本文件的绝对路径记为 `skill_path`。

**进入时做一次**：
1. 按第 1 步侦察，台账头部写 `mode: standing`、`skill_path: <本文件绝对路径>`、`batch: 0`。已有台账且头部是 `mode: standing` 时是恢复，不重做侦察，只复查仓库状态和资源。
2. **接管已有会话**：子会话看不到本会话的聊天记录。把之前对话里和后续工作有关的内容写进台账“接管背景”区：已做完的事（附分支或提交）、已定下的决策和约束、用户偏好、未完成的事项。不超过 20 行，只写结论；之后派发时从这里摘需要的部分写进说明。
3. **建待办池**：把总目标（用户说过的整体目标，没有就写“未声明”）写进台账头部 `总目标`；把“接管背景”里未完成的事项、用户提过但还没做的事写进台账“待办池”，每条附来源。
4. **无目标进入**（`/hq --stay` 后面没有目标，或用户只说“常驻”没给目标）：
   - 探索项目，找出值得做的任务。按“推荐下一批”的来源收集候选，另外补看：README 和 docs 的定位与路线图、最近约 20 条 `git log --oneline`、未合并的分支、测试和 lint 能否跑通（只跑轻量的检查，重的派出去）、依赖或文档明显过期的地方。
   - 主会话只读台账、PLAYBOOK 和目录结构；项目较大（文档加代码超过几十个文件）时，派一个 T1 只读调研子任务（宿主有只读子代理类型就用它）做探索，要求它返回带来源的候选清单，不要它的读码过程。
   - 按“推荐下一批”的筛选和输出规则给出推荐（编号，最多 5 条），末尾写“回复编号（如‘做 1、3’）、‘按推荐’全部执行，或直接说你的目标”。**进入时一律等用户选择，不自动开始**，即使 PLAYBOOK 是 `autonomy: auto`。
   - 用户选了编号或回复“按推荐”：把选中的条目合成本批目标，记 `from_recommendation: true`，开第 1 批；用户给了自己的目标：按目标开第 1 批，推荐留在待办池。
   - 一条可执行候选都没找到：说明“探索后没有发现明确的待办任务”，列出检查过的来源，请用户给目标。此时还没有总目标，不要说“项目任务已全部完成”。

**每一批**：
- 用户的下一句话是新目标时开新一批：`batch` 加 1，生成新的 `run_id`，从第 0 步开始（侦察只补查变化：`git status`、基线、资源）。第 0 步照常判断：小目标直接做，不硬拆；用户明确说“这批也全部派出去”时才例外。
- 用户只是提问或闲聊：照常回答（进度从台账取），不开新批，不退出常驻。
- 一批结束（第 9 步记录、第 10 步汇报）后**不退出**：先按下面的“推荐下一批”给出推荐或完工声明，再写“常驻中，等待下一个目标”；把这批的任务表压缩成一行（run_id、目标、结果、分支）移到台账“历史批次”区，完整内容留在 `.hq/runs/<run_id>.jsonl`，保持台账短小。
- 上一批还有任务在跑时就收到新目标：可以并行开新一批，新任务不能改上一批未完成任务的归属文件；有冲突就排在后面。
- run 记录加 `standing_seq`（本会话第几批）、`from_recommendation`、`recommended_next`。

**推荐下一批**（每批汇报之后做）：
- **收集候选**，只用便宜的来源，不亲自大面积读代码（铁律 1）：
  1. 台账：“待办池”、未派发的衍生任务、`BLOCKED`/`FAILED` 任务、“待问用户”里已有答复的事项、审核时记下的后续问题。
  2. 会话：“接管背景”的未完成事项、总目标里还没覆盖的部分、用户在对话中提过但没排进批次的要求。
  3. 计划清单（有 `plan/backlog.json` 时，见下面“按计划执行”）：依赖已满足、状态 `todo` 的任务，当前版本优先。
  4. 项目：README/docs 里的路线图或待办、CHANGELOG 中“待验证”且需要动手验证的项、`git grep -n -E "TODO|FIXME"` 的计数和前几条、仓库的 open issue（宿主能查时）、本批合并后全量测试的失败项。
  候选来源多、要读的内容大时，派一个 T0/T1 只读调研子任务汇总，不要自己读。
- **筛选**：只保留有证据的候选，每条写来源（台账哪一区、哪个文件第几行、哪个 issue）。不为凑数编任务；属于停止条件的（要密钥、要部署、要用户操作）单独列为“需要你处理”，不算可执行任务。已完成的、与总目标无关的低价值项不推荐。
- **输出**：最多 5 条，编号，按“关键路径/依赖优先，其次价值高、风险低”排序，每条一行：编号 | 标题 | 来源 | 预计档位和用时 | 为什么现在做。末尾写“回复编号（如‘做 1、3’）、‘按推荐’全部执行，或直接说新目标”。PLAYBOOK `autonomy: auto` 且用户说过“按推荐自动继续”时，不等回复直接开下一批（仍受第 0 步和停止条件约束）。
- 推荐结果写进台账“待办池”（新的放前面，已做的删掉），这样压缩或换会话后也不丢。
- **完工判断**：候选筛完后一条可执行的都没有，并且总目标的验收标准都已满足（或总目标未声明而待办池为空），就明确告诉用户：“项目当前所有任务都已执行完毕，没有更多可执行任务了。”后面附：检查过哪些来源、总目标的验收结果、仍需用户处理的事项（如有）。不要在有可执行候选时说完工。完工后仍保持常驻，等用户的新目标，或问一次是否退出常驻。

- 项目缺计划、需求或架构文档，而且这正挡着后续工作时，推荐里可以写“建议运行 `/hq-plan`”这类阶段命令，作为一条普通推荐，**不自动运行**（阶段技能只在用户输入命令时执行）。有文档目录时，用 `scripts/stage-status.py --docs <docs_root>` 看各阶段的状态再推荐；一个版本的任务全部完成时，推荐运行 `/hq-launch`。

**防止压缩后忘记**：每个用户回合开始时，若台账头部是 `mode: standing`，而你已不记得本文件的流程细节（上下文被压缩或会话恢复），先重新读取 `skill_path`，再读台账，然后继续。

**退出**：用户说“退出常驻”“结束司令部”或 `/hq --stop`。等在跑的任务收尾（或按用户要求停掉），台账头部改为 `mode: off`，做一次最终汇报。

## 按计划执行（可选）

`/hq-plan` 产出的计划清单（`<docs_root>/plan/backlog.json`，格式见 `references/backlog-schema.md`）可以直接执行。
- **进入**：`/hq --backlog [清单路径] [版本或任务编号，如 R1、B-003,B-004]`，或目标里明确说执行计划里的版本或任务（如“执行 R1”）。路径默认取 PLAYBOOK `docs_root`（没写就是 `docs/`）下的 `plan/backlog.json`；没给版本时取第一个还有 `todo` 任务的版本。可以和 `--stay`、`--assist` 连用。
- **先检查**：运行 `python3 <scripts 目录>/backlog-check.py <清单路径>`。选中范围内有错误就不执行，汇报错误并建议运行 `/hq-plan` 补全；错误只在其他版本时照常执行，汇报里提一句。
- **`hold` 任务从不派发**：它们在等别人的决定（如客户确认范围变更），不进任务图，也不因为“被依赖”而纳入本批（`backlog-check.py` 已把依赖 hold 任务的情况报成错误）。汇报里单列“暂缓（等待中）”：编号、标题、`hold_reason`。用户说已确认时，把状态改回 `todo` 再派发；用户说不做时改成 `dropped`。
- **第 2 步**：选中的 `todo` 任务就是任务图；依赖的任务还不是 `done` 的，一并纳入本批。仍按第 2 步打包小任务、拆大任务，拆出的子任务编号写成 `B-003a`、`B-003b`。`owns` 写的是模块编号时，侦察时落到具体文件。任务的 `acceptance`、`verify_level`、`verify_cmd` 直接作为说明里的验收标准和验证。有 `ready_after` 的任务在里程碑就绪前不派发（就绪与否问 `owner`，或看用户是否已告知）；`needs_human` 的任务按第 4 步第 0 条处理。
- **第 3 步**：清单里的 `tier` 只是计划时的预估。按当前代码重新打分选档；task 记录写 `plan_tier`（清单里的档位），和实际选的档位不同时在 notes 写一句原因。
- **第 8 步之后**：回写清单：任务 `status` 改成 `done` 或 `blocked`，填 `run_id`、`branch`，更新顶层 `updated`；再跑一次 `backlog-check.py`，随本批改动一起提交。清单以外的新任务不写进清单，记进台账；要改计划时建议用户运行 `/hq-plan`。
- 没有清单、目标又是“规划”“排期”这类时，不自动转成 `/hq-plan`，按普通目标处理，汇报里可以建议它。

## 第 0 步：要不要编排

满足任一条就**不编排**，直接在当前会话做（最多派 1 个子代理）：
- 预计总工作量不到约 30 分钟；
- 各部分高度耦合，拆开后接口协调比干活还费事。

理由：每开一个子会话都有固定开销。实测一个翻译 56 行文档的子代理消耗约 7.3 万 token，大部分花在熟悉项目上。

## 第 1 步：侦察（启动时做一次，结果写进台账头部）

- **先读 `.hq/PLAYBOOK.md`**（本项目的经验和授权配置）。没有就按 `references/playbook-template.md` 建一个空的。
- **识别宿主**（按特征判断，结果写进台账头部）：
  - **claude-code**：工具列表里有名为 Agent 的子代理工具，或有 Claude Code 远程会话工具（工具名以 claude-code-remote 开头）。若环境变量 `ANTHROPIC_BASE_URL` 指向 deepseek，另读 `references/hosts/deepseek.md`。
  - **codex**：能看到 `~/.codex/`、能用 codex 的子代理功能。读 `references/hosts/codex.md`（接 DeepSeek 后端时另读 `hosts/deepseek.md`）。
  - **dsh**（DeepSeek Harness）：工具列表里有 `subagent`、`list_subagent_models`、`list_agents`，或存在 `~/.dsh/`、`$DSH_HOME`。读 `references/hosts/dsh.md`；`$DSH_HOME` 非默认时把上面 find 的 `~/.dsh/skills` 换成 `$DSH_HOME/skills`。
  - **opencode**：工具列表里有 `subagent`（参数为 agent ID、`description`、`prompt`、可选 `sessionID`，没有 `list_subagent_models`），或系统提示表明是 OpenCode，或存在 `.opencode/`、`~/.config/opencode/`。读 `references/hosts/opencode.md`（子代理和主会话共用工作目录，改代码任务要先建 worktree）。
  - **gemini**：系统提示表明是 Gemini CLI，或工具列表里有 `activate_skill`、`run_shell_command`，或存在 `.gemini/`、`~/.gemini/`。读 `references/hosts/gemini.md`（子代理同步执行、与主会话共用工作区，改代码任务要先建 worktree）。
  - **cursor / other**（Cursor 及其他支持 SKILL.md 的工具）：读 `references/hosts/generic.md`，按其识别表记 host；有 shell 且 `worker_clis` 允许时用 W，否则用降级模式。
  - 识别后读对应的 `references/hosts/<host>.md`，按其能力表使用下面的抽象能力。
- **我在哪**：宿主文档说明怎样判断云端会话还是本地；只有云端会话通常才有 remote_workers 和 local_machine。
- **有哪些派发通道**（通用规则见 `references/runtimes.md`，具体调用见宿主文档）：
  - **A 进程内子代理**：spawn_worker 的进程内形式，可设模型、思考深度、worktree 隔离、后台运行。
  - **B 云端子会话**：remote_workers，通常只在云端会话里有。
  - **C 用户电脑**：local_machine，云端会话连上用户电脑后在那里执行。
  - **D 从本地 CLI 发起云端任务**：先确认 CLI 支持再用，监控能力弱。
  - **W CLI 子进程 worker**：`scripts/cli-worker.sh` 在独立 git worktree 里后台运行 codex、claude、opencode、gemini 或 cursor 的命令行，任何有 shell 的宿主都能用（各 CLI 的沙箱映射见 `references/runtimes.md` W 节）。**何时用**：宿主没有合适的子代理能力；需要真正的进程隔离；PLAYBOOK 授权区开启了跨厂商 worker（`worker_clis`）。
- **降级模式**：宿主没有子代理能力、也用不了 W 时，主会话按同样的计划、台账、质量门槛**串行**亲自执行，仍然记录数据，channel 记 `main`。此时**暂停铁律 1**（“不做重活”），其余铁律照常；每个任务做完就更新台账，控制上下文。
- **仓库**：`git remote -v`、默认分支、`git status`。未推送的改动远程子会话看不到。
- **资源基线**：先读 `~/.hq/skill-path`（安装脚本写入的 hq 技能目录），其下 `scripts/resources.sh` 存在就用它；否则用 shell 查找：`find ~/.claude/skills ~/.claude/plugins ~/.agents/skills ~/.dsh/skills ~/.config/opencode/skills ~/.cursor/skills ~/.gemini/skills ~/.gemini/extensions/hq-orchestrator/skills .claude/skills .agents/skills .dsh/skills .opencode/skills .cursor/skills .gemini/skills -path '*hq/scripts/resources.sh' 2>/dev/null | head -1`。执行 `bash <路径> 1500 1`。同目录的 `cli-worker.sh` 用同样方式找。
- **辅助执行者**（开启时）：先运行 `python3 <scripts>/assist-config.py check --project . --json`，拿到合并后生效的设置（`effective`，再叠加本次 `--assist` 参数）、错误和提醒：模型不在 codex 模型目录里、思考深度不被该模型支持的 profile 按“不可用”处理（`unavailable:bad_model`），即将下线的模型只在汇报里提醒。然后去掉与主宿主相同的 profile（规则 10，例如 Codex 宿主上的 `codex`），再逐个检查剩下的能不能用——CLI 在 PATH 上（`command -v`）、`env_file` 存在且权限 600、目标 CLI 已登录或有密钥；辅助都走 W 通道，还要确认本会话能建 worktree（`git worktree add` 要写 `.git`，Codex 等宿主的沙箱可能禁止），不能建就整个名单按“不可用”停用。不能用的从本次名单去掉，台账“决策”区记一行原因，不停下问用户（全都不能用时，在第一次汇报里说明一次）。云端会话里还需要放行接口主机、配好密钥，见 `references/hosts/kimi.md` 第 4 节。
- **预算**：远程并发上限取 PLAYBOOK 的 `remote_concurrency`（默认 4；宿主有更低的 concurrency_limit 时取低者）、每任务最多 2 次失败、单批子任务数上限取 `max_subtasks`（默认 12）、金额上限取 `budget_usd`（没写就不设）。要超出时按“停止条件 2”处理。并发上限只决定同时开几个，不影响每个任务的档位（铁律 8）。
- 生成 `run_id`（如 `20261124-1530-<目标缩写>`），写进台账。

## 第 2 步：规划成任务图（DAG）

- **并行以缩短总用时为准**：总用时最短只能压到关键路径的长度，所以优先缩短关键路径，而不是增加并行数。
- **打包优先**：几个小而相关的任务打包给一个子会话。只有任务够大（约 15 分钟以上）、改的文件不重叠，才拆开并行。
- **难度单一**：每个任务内部难度要一致，不要把“机械改名”和“找根因”塞进同一个任务，否则档位要么浪费要么不够，后面还得调档。
- **文件归属**：并行任务不能改同一个文件。共享接口、类型、配置先单独拆成前置任务。
- 每个任务记录：id、标题、依赖、归属文件、验收标准、验证级别和命令、重任务还是轻任务、预计时长。
- 调研类任务（只读）优先派出去，它们的结论决定后面怎么拆。
- **围绕外部里程碑排**：要等账号开通、真机到位、客户资料这类外部条件的任务（计划清单里的 `ready_after` 里程碑和 `needs_human`），不要假设一开始就都齐了。先排不依赖它们的任务；把“请用户/客户准备 X”尽早列进第一次汇报的“需要你处理”，让等待和开发并行；里程碑没就绪时，依赖它的任务标 `BLOCKED`（备注写在等哪个里程碑），其余照常推进。
- 计划写进台账后，作为通知发给用户（任务表、档位、位置、并发、预计用时和消耗），**不等确认**，直接进入派发（PLAYBOOK 设了 `autonomy: confirm-plan` 时才等）。

## 第 3 步：选档（模型和思考深度）

按 `calibration.md` 的 5 维打分表和 T0–T4 抽象档位选档，再按宿主映射（宿主文档第 3 节；PLAYBOOK“选档偏好”里有本宿主的映射时优先）换成具体模型和思考深度，并应用修正规则。首次在新宿主上运行时，把实际用的映射写进 PLAYBOOK“选档偏好”。跨厂商 worker 只在 `worker_clis` 开启时使用。要点：
- 选档算上失败重来的成本：需求明确的选最低能胜任的档位；模糊或高风险的直接用够强的档位，争取一次做对。
- **拿不准就往上选**（所有宿主，`calibration.md` 规则 9）：低成本宿主上调一整档；Claude Code 这类高成本宿主默认只把思考深度上调一级，模糊度 ≥1 或风险 2 时上调一整档。上调的在 notes 记 `bias:+1(tier|effort)`。
- **并发要求不改档位**（`calibration.md` 规则 11）：“尽量多开”、任务多、槽位或预算紧张、限流，都只调并发和排队，不降模型或思考深度；用户明确授权“为多开可以用低档”时才按规则 11 降，notes 记 `downgrade:user_allowed(-N)`。
- 难度看不准（模糊度 2 分）时，先派短小的调研子会话消除不确定性，再按实际难度派实现任务。
- 选档理由在台账备注里写一句，方便用户纠正。
- **辅助执行者开启时**：打完分、选好档后，按 `calibration.md` 规则 10 决定这个任务给主宿主还是给辅助；给辅助的，模型取该 profile 对应档位的模型，台账“模型/深度”列写 `<profile>:<模型>`。
- 档位表和修正规则只在 `calibration.md` 里维护，复盘只调那个文件，本文件不重复。

## 第 4 步：选运行位置

按顺序判断，命中就停：

0. **需要人或真实环境**（计划清单里有 `needs_human`，或任务要真机、iOS 构建签名、商店账号、支付测试账号、客户资料、人工核对）：**不整个交给云端子会话**。拆成两半：
   - AI 能做的准备（脚本、测试用例、检查清单、要填的表）照常派给 worker，按第 3 步选档；
   - 需要人的那一步（`human_step`）：用户电脑能做的（本机已连真机、已登录账号）用 C；否则主会话按停止条件 1 停下，把准备好的材料和要做的那一步一次交给用户。
   - 任务保持 `BLOCKED`，台账备注写清在等什么、材料在哪个分支；用户回报结果（截图、日志、“已通过”）后再按第 8 步审核，审核通过才改成 `DONE`。不要用模拟器、假账号或“看起来能过”代替这一步。
1. **必须在本地执行**：需要用户电脑上才有的东西（仓库外的本地文件、本地数据库或服务、GUI、模拟器、USB、GPU、VPN 或内网、本机登录态、只能在 macOS/Windows 构建、未推送的本地改动）。主会话在本地用 A 或 W；在云端用 C，连不上就标 `BLOCKED`，其余照常推进。
2. **适合远程（B）**：耗时长、能并行、仓库在 GitHub、只依赖已推送的代码。
3. **适合进程内（A）**：小任务（约 10 分钟内）、需要和主会话紧密往返、需要当前工作区状态、没有 B。
4. **适合 W**：宿主没有合适的子代理能力、需要真正的进程隔离，或要用跨厂商模型（需 `worker_clis` 授权，或第 3 步按规则 10 派给了辅助执行者）。辅助任务一律走 W：`cli-worker.sh start … --cli <profile.cli> --model <模型> --label <profile> [--env-file <profile.env_file>]`。
5. 其余：主会话在云端优先 B，在本地优先 A；都没有就 W，再没有就降级模式。

## 第 5 步：并发控制

- **本地槽位**（A、C、W 的重任务）：每次派发前运行 `resources.sh`，重任务 `1500 1`，轻任务 `400 0.25`。
  - `new_local_slots` 是在当前占用上还能再开几个。新任务 30 到 60 秒后才拉高负载，连续派发时把最近 60 秒内新开的任务从槽位里扣掉。
  - `YELLOW` 最多再开 1 个；`RED` 不再派发。`UNKNOWN` 表示有读数读不到（如沙箱禁止 `sysctl`，见输出的 `unreadable`），不代表资源紧张：按 `YELLOW` 处理，最多再开 1 个，台账“资源基线”写明哪些读不到。`RED` 且内存可用低于 5% 或交换区持续上涨：用 stop_worker 停掉最近启动的重任务，放回队列，台账记一次 `throttle_events`。
- **限 CPU**：说明里写明并行度（`make -j2`、`pytest -n 2`、`--maxWorkers=2`）。用户电脑同一时间最多 1 个任务跑全量构建或测试。
- **远程槽位**：不占本地资源但消耗额度，并发不超过预算上限和宿主的 concurrency_limit。
- 每当有任务完成、失败或巡检时，重新算槽位，从就绪队列按“关键路径优先，其次难度高的优先”补位。
- **用户要求“尽量多开”**：把并发开到本地槽位、远程上限和预算允许的最大值，但每个任务仍按第 3 步的档位派发；槽位或额度不够时排队，**不为多开而降档**。遇到限流（429）先降并发，不撤销规则 9 的上调。

## 第 6 步：派发

- 说明必须让子会话不依赖主会话上下文也能独立完成，按 `references/brief-template.md` 写，必填项不能省，包括验证级别和检查点规则。
- 用 spawn_worker 派发（具体调用见宿主文档）。分支：每个改代码的任务用独立分支 `hq/<任务id>`。A、W 用 worktree 隔离；B 指定产出分支 `hq/<id>`，基于已推送的基线。
- **派 worktree 任务前**：确认宿主的 worktree 目录（见宿主文档；W 见 `cli-worker.sh`）已被 git 忽略（`git check-ignore -q <目录>/x`），没有就写进 `.git/info/exclude`。否则临时目录会显示成未跟踪文件，可能触发 hook 或被误提交。合并后用 `git worktree remove` 清理，并删掉临时分支。
- 降级模式不派发：主会话按同一份说明亲自做，同样遵守归属文件和验证级别。
- 派发后立即在台账记下：通道、模型、深度、worker id、分支、开始时间、预计时长。

## 第 7 步：监控与动态调档

**监控**
- 用 monitor 看状态。宿主会在 worker 完成时自动通知的（如 A），不要轮询。
- 不保证完成通知的（如 B、D、W）：说明里要求 worker 按 message_worker 回报（W 没有回报通道，结果写在交付格式里），主会话用 schedule_checkin 设兜底巡检，巡检时用 monitor 看全局和单个任务状态。没有 schedule_checkin 时，在主会话每个回合检查一次。
  - **巡检间隔按预计时长定**：约为预计时长的 1 到 1.5 倍，最短 3 分钟，最长 30 分钟。还在正常运行时，下次间隔取剩余预计时长。
  - 回报一到就进入审核，并取消未触发的巡检。
  - 巡检时除了看是否完成，也看是否卡住：状态是 `blocked` 且 `need_input` 时，worker 多半在等权限批准（如发回报），不是在干活。读 `needs_action` 确认等的是什么，再决定是告诉用户去批准，还是直接按交付文件和分支审核。
- worker 来提问：能用已有信息回答的用 message_worker 回复；需要用户的按“停止条件”攒起来一次问。
- 跑偏（越出归属文件、陷入循环）：先用 message_worker 纠正；无效就 stop_worker，改说明后重派。
- 用户问进度时，从台账给一张简表。不要编造还没返回的结果。

**动态调档**（子会话启动后，主会话改不了它的模型和思考深度）
- 从源头减少调档：第 2 步让任务难度单一，第 3 步看不准就先调研。
- **检查点**：说明要求子会话在以下情况发 `CHECKPOINT`（有 message_worker 的用它发，没有的提前返回）：衍生出超出范围的任务；实际难度明显高于档位；同一问题失败 2 次以上。报告写：发现了什么、建议档位、打算继续还是停下。
- **分诊**：
  - 范围内的小衍生任务：子会话直接做，不用汇报。
  - 超出范围或分量大的：子会话不做（防漂移）；主会话评估难度后另行派发，能并行就立即派。
  - **卡住**（同一问题失败 ≥2 次，或用时超过预计 2 倍）：子会话先写交接说明（做到哪、试过什么、分支），主会话用高一档的模型新开子会话，从这个分支接着做。
  - **不做降档交接**：交接丢上下文，重新熟悉项目的开销大于降档省下的钱。
  - **建议用户手动调档**：只在换会话代价太高、子会话又确实卡住时用。一次给出明确建议（打开哪个会话，切到什么模型），并注明运行中的会话能不能改思考深度取决于界面是否提供这个选项。话术见宿主文档。
- 每次升档、交接、衍生任务、检查点都记进台账，并计入第 9 步的 task 记录。

## 第 8 步：审核与归并

**质量门槛**（三项都过才算合格；用时不算质量，归入效率指标）：
1. **不漂移**：没改出允许的文件，没做目标以外的事，验收标准中途没被改。
2. **验证到位**：有验证证据，且通过。
3. **问题少**：审核、合并、用户三个环节发现的问题按严重程度计数，越少越好。

**验证分级**（按风险，不要求每个子会话都跑全量测试；级别写进说明）：

| 级别 | 适用 | 子会话做 | 主会话做 |
|---|---|---|---|
| doc | 文档、配置 | 机械检查（格式、链接、行数） | 看 diff |
| code | 普通代码 | 受影响部分的测试、lint、类型检查 | 看 diff 和证据 |
| high | 数据、安全、并发、公开 API | 上一级 + 补回归用例 | 逐个复跑验收命令；合并后另派独立审核 |
| e2e | 需要本地环境的端到端 | 不跑 | 合并后统一跑一次 |

步骤：
1. **看报告**：必须按模板交付，缺验证证据的视为没完成。
2. **查漂移**：`git fetch origin hq/<id>`，`git diff --stat`，确认没越出归属文件。只有 high 级任务才由主会话逐个复跑验收命令。
3. **独立审核**（high 级，或 T3 及以上，或改动超过约 300 行；辅助执行者的产出超过约 150 行）：另派只读审核子代理，只给代码和验收标准，不给实现者的结论。
4. **归并**：按 DAG 拓扑顺序合进 `hq/integration`，然后主会话统一跑一次全量测试（有 e2e 的也在这时跑）。小冲突自己解决，大冲突派子任务。
5. **收尾**：通过的标 `DONE`，按宿主文档归档或停止 worker（B 归档会话，W 用 `cli-worker.sh stop`），worktree 按第 6 步清理。不通过的按 `calibration.md` 的失败规则处理。
   - **远程 `hq/*` 分支**：确认已完全合入（`git merge-base --is-ancestor origin/hq/<id> <目标分支>`）后再删。有的宿主可能不允许删除远程分支（如云端会话报 `unexpected disconnect` 或 `remote end hung up`），试一次就停，不要反复重试或绕路，把没删掉的分支列进汇报，交给用户删除。
6. 合入默认分支、开 PR：按 PLAYBOOK“授权”区的 `merge_default`、`open_pr`，默认 `ask`。

## 第 9 步：记录数据与小结

- **每个任务结束时**往 `.hq/runs/<run_id>.jsonl` 追加一行 `type:"task"`，**整批结束时**追加一行 `type:"run"`。只用手头已有的信息，**不为记录数据额外派子会话**。字段定义以 `references/metrics-schema.md` 为准，主会话直接追加；`scripts/metrics.py` 只读取汇总，写完可运行一次确认能读、损坏行数为 0。要点：
  - task：run_id、task_id、host、kind、risk、tier_score、tier、plan_tier（按计划执行时）、model、effort、channel、est_min、actual_min、tokens、cost_usd、attempts、tier_changes、handoffs、derived_tasks、checkpoints、user_manual_adjust、scope_violation、drift、verify_level、verify_evidence、verify_pass、issues{review, integration, user, severity_max}、review_outcome、user_corrections。
  - run：host、wall_min、critical_path_min、tasks、max_concurrency、throttle_events、autonomy_stops、decisions、integration_pass、plugin_version。
  - 用量：用 worker_usage 读取（具体见宿主文档）。`cost_usd` 是主要成本指标；`tokens` = input + output + cache_write，不含 cache_read（口径见 schema“用量口径”）。分不出缓存读取时 tokens 填 `null`、原值记进 notes。拿不到就填 `null`，不要猜。降级模式的 channel 记 `main`。
  - 跨厂商：用到非宿主自带的模型时，model 写成 `<cli>:<模型名>`。
  - 辅助执行者：task 记录写 `assist: <profile>`（主宿主自己做的写 null），model 写成 `<profile>:<模型名>`；辅助失败被主宿主接手时，这条 task 的 `handoffs` 加 1、`tier_changes` 记一次，`assist` 仍写原来的 profile。
- 本地运行时，同时追加一份到 `~/.claude/hq/runs/`（非 Claude Code 宿主也用这个目录，便于统一复盘），用于跨项目累积。
- **保存进仓库**（PLAYBOOK `runs_persist`）：`branch` 时整批结束后运行同目录的 `scripts/runs-persist.sh save branch`（写进专用分支 `hq/runs` 并推送，不碰工作区）；退出码 3（推不上去）就改用 `save commit`，并把 PLAYBOOK 改成 `runs_persist: commit`。`commit` 时直接 `save commit`（提交到当前分支，随本批改动一起推）。云端运行且 PLAYBOOK 没写这项时，第一次汇报里问用户一次（推荐 `branch`），答案写进 PLAYBOOK，不再问；本地没写就是 `off`。
- **小结**：每批结束后在台账“小结”区写 3 到 5 行要点，并把本项目特有的经验更新进 `.hq/PLAYBOOK.md`（模板 `references/playbook-template.md`；最多 30 条，每条附证据，新的替换旧的）。
- 累计约 5 次运行或 20 个任务时，在汇报里提示用户运行 `/hq-retro` 做复盘校准。

## 第 10 步：汇报

阶段性和最终汇报都要简短：完成了什么（附分支名）、怎么验证的、做了哪些关键决策和假设、哪些还卡着或需要用户决定（按停止条件一次性列出，附推荐选项）、档位分布和按模型统计的消耗、没删掉的远程分支、是否该跑 `/hq-retro`。

## 自主决策与停止条件

**决策协议**（技术方案、用户体验、模型、拆分、重试全部自主决定）：
- 调研力度和决策分量相称：小决策直接看代码库现有约定；影响大的才派调研子会话。
- 选择顺序：正确性 > 用户体验 > 与代码库的一致性和可维护性 > 简单 > 成本。
- 两个方案难分高下时，选更容易撤回的那个。
- 每个决策在台账“决策”区记一行：考虑过哪些方案、选了哪个、为什么。

**只有以下情况才停下来找用户**（每次计入 `autonomy_stops`）：
1. 需要密码、密钥、账号、付款，或需要用户在界面上、在自己电脑上操作。
2. 不可撤回或会影响别人的操作，且没有事先授权：删除数据或分支、部署、强制推送、对外发消息或发布、超出预算。
3. 需求有歧义，调研后仍判断不了，且猜错的返工代价超过约 1 小时。否则选最可能的解释继续做，把假设记进“决策”区。

停下时：把问题攒在一起一次性问，每个问题附推荐选项；同时继续推进不受影响的工作。

**授权配置**（写在 `.hq/PLAYBOOK.md` 的“授权”区）：
- `merge_default: auto-if-gates-pass | ask`（默认 `ask`）：质量门槛通过后是否自动合入默认分支。
- `open_pr: auto | ask`（默认 `ask`）。
- `budget_usd: <数额>`：单次运行的花费上限，超出前按停止条件 2 处理。
- `remote_concurrency: <数>`（默认 4）：远程子会话（B 通道）同时运行的上限；本地槽位仍按第 5 步的资源检查。调高前确认审核和归并跟得上，否则任务会堆在审核环节。
- `max_subtasks: <数>`（默认 12）：单批最多派多少个子任务。按计划清单整版推进（`--backlog`）时可以设成该版本的任务数。
- `autonomy: auto | confirm-plan`（默认 `auto`）：`confirm-plan` 时第 2 步的计划要等用户确认再派发。
- `worker_clis: [codex, claude, opencode, gemini, cursor]` 中的若干项（默认空，即关闭）：允许 W 通道使用哪些 CLI 做跨厂商 worker；宿主自己的 CLI 不需要列。
- `runs_persist: off | branch | commit`（本地默认 `off`，云端没写时问一次）：运行记录是否保存进仓库，见第 9 步。
- `assist`（默认关闭）：辅助执行者的名单、最高档位和各自的 CLI、模型、`env_file`，见上文“辅助执行者”和 `calibration.md` 规则 10。也可以写在用户级 `~/.hq/config.yaml`（所有项目共用），项目里写了的项优先；用 `scripts/assist-config.py set` 或 `/hq --assist … --save` 写入。`assist.use` 里的 profile 视为已授权，它用的 CLI 不必再列进 `worker_clis`。

## 台账格式（`.hq/LEDGER.md`）

```markdown
# HQ 台账 — <目标>
mode: single/standing | skill_path: <常驻时填> | batch: <常驻时填> | 总目标: <常驻时填>
run_id: <run_id> | 自主级别: 自动（停止条件 1–3）| merge_default: ask | open_pr: ask | budget_usd: - | assist: off
宿主: claude-code/codex/dsh/opencode/cursor/gemini/other（降级） | 环境: 云端/本地 | 通道: A,B,C,W | 仓库: <remote> 基线 <branch>@<sha> | 预算: 远程≤4 失败≤2
资源基线: <resources.sh 输出>

| id | 标题 | 依赖 | 档位 | 模型/深度 | 位置 | 验证级别 | 状态 | worker id | 分支 | 尝试 | 预计/实际(分) | 备注 |
|----|------|------|------|-----------|------|----------|------|-------------|------|------|---------------|------|
| t1 | ...  | -    | T2   | sonnet/medium | B | code | RUNNING | session_... | hq/t1 | 1 | 20/- | 选档理由 |

状态取值: PLANNED / READY / RUNNING / REVIEW / DONE / FAILED / BLOCKED
## 接管背景（常驻模式接管已有会话时填，≤20 行）
## 待办池（常驻模式：标题 | 来源 | 预计档位/用时，新的在上）
## 历史批次（常驻模式：每批一行 run_id | 目标 | 结果 | 分支）
## 决策（方案 | 选择 | 理由）
## 待问用户（攒齐一次问，附推荐选项）
## 调档、交接与衍生任务
## 小结
## 事件日志（最新在上）
```
