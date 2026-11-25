# 宿主适配：OpenCode

## 1. 概述与适用版本

- 适用：OpenCode V2（`opencode` CLI/TUI、桌面端等前端共用同一后台服务）作为 hq 的**原生宿主**。OpenCode 的子代理可以在 agent 文件里各自指定 `model: provider/model#variant`，所以给 T0–T4 各建一个子代理 `hq-t0…hq-t4`，档位就能逐任务生效。
- 核实状态（2026-11-25）：**只读了官方文档源码**（GitHub `sst/opencode` 仓库 `services/site/src/docs/content/` 下的 `agents.mdx`、`tools.mdx`、`models.mdx`、`skills.mdx`、`config.mdx`、`cli/commands.mdx`、`migrate-v1.mdx`，2026-11-25 的提交），**没有安装、没有实机运行**。V1 的文档另有一套（`agent/` 目录、`permission`/`tools`/`temperature` 等字段），V2 仍兼容读取但已弃用；本文件只按 V2 写。
- **技能发现**：个人 `~/.config/opencode/skills`，兼容 `~/.claude/skills`、`~/.agents/skills`；项目 `.opencode/skills`，兼容 `.claude/skills`、`.agents/skills`（从当前目录向上到项目根）。同 ID 的技能后注册的生效。技能目录里的相对路径相对于 `SKILL.md` 所在目录。子代理也会加载技能。
- **识别特征**：系统提示或工具说明表明是 OpenCode；工具列表里有 `subagent`（参数含 agent ID、`description`、`prompt`、可选 `sessionID`）；存在 `.opencode/` 或 `~/.config/opencode/`。注意 dsh 也有名为 `subagent` 的工具，但 dsh 的参数是 `provider`/`model`/`reasoning_effort` 并配有 `list_subagent_models`，以此区分。

## 2. 能力表

| 能力 | 怎么做 | 不支持时的降级 |
|---|---|---|
| spawn_worker | `subagent` 工具：agent 填 `hq-t0`…`hq-t4`（按档位），`description` 写任务标题，`prompt` 写完整任务说明。调用立即返回 `sessionID`，子代理在后台运行。只有 `mode: subagent` 的 agent 能被派发；默认嵌套深度 1（子代理不能再派子代理，正合 hq）。**首次运行先确认 `hq-t*` 存在**（见第 4 节），不存在时用内置 `general`（档位不生效，notes 记 `tier:not-applied`） | 子代理不可用：W 通道（`cli-worker.sh start --cli opencode ...`）或降级模式（见 `generic.md`） |
| monitor | 子代理空闲时父会话会收到 `<subagent>` 消息，之后每轮工作结束再收到一次；**不要轮询**。需要总览时用 shell：`opencode session list --format json` | 等通知 |
| message_worker | 再次调用 `subagent`，带上返回的 `sessionID`，就是给同一个子会话发后续消息；子代理还在运行时，消息并入它当前这一轮。用于回答 CHECKPOINT、纠偏 | — |
| stop_worker | 待核实：文档没有写中止单个子代理的工具。`opencode session delete <id>` 会删除会话及其子会话，是否能中止运行中的子代理未写明，**不要默认使用**（不可逆） | 不再给它发消息，等它结束后不合并其结果；需要时请用户在界面里停止 |
| worker_usage | 待核实：`opencode session export <sessionID>` 输出会话 JSON，其中 token/成本字段名未在文档中给出；`opencode stats --cost --json` 只有汇总（可加 `--project .`、`--days`）。tokens 口径同 runtimes.md（input + output + cache_write，不含 cache_read） | 拿不到就 tokens、cost_usd 填 null，不估算；可在 run 级 notes 记一次 `opencode stats --cost --json` 前后差值 |
| schedule_checkin | 文档未提供定时唤醒 | 依赖 `<subagent>` 通知；长时间无通知时主会话在下一回合用 `opencode session list` 检查 |
| remote_workers | 不支持（OpenCode Console 不在本适配范围） | 只用本地子代理或 W |
| local_machine | 不适用：OpenCode 在本地运行 | — |
| concurrency_limit | 文档没有写并行子代理上限；按 `resources.sh` 的本地槽位控制。嵌套深度由 `experimental.subagent_depth` 控制（默认 1，不要调高） | — |

### 隔离（重要）

`subagent` 工具**没有 worktree 参数**，子代理和主会话在同一个工作目录里。所以：

- **改代码的任务**：派发前由主会话建 worktree：`git worktree add .hq/worktrees/<id> -b hq/<id> <基线>`（先确认 `.hq/worktrees/` 已被 git 忽略，规则同 SKILL.md 第 6 步），任务说明第一行写 `工作目录: <绝对路径>`；`hq-t*` 模板已要求子代理只在该目录内读写。
- 派发后和合并前各检查一次主工作区：`git status --porcelain` 与派发前一致；不一致说明子代理越界，按“问题”记录并回滚越界改动，再决定是否重派。
- 只读调研任务可以不建 worktree。

## 3. 档位映射

| 档位 | 子代理 | 模型档次 | variant（思考深度） |
|---|---|---|---|
| T0 | hq-t0 | 最快的小模型 | low |
| T1 | hq-t1 | 快速的中档模型 | low |
| T2 | hq-t2 | 中档模型 | medium |
| T3 | hq-t3 | 最强模型 | medium |
| T4 | hq-t4 | 最强模型 | high |

- 模型写在 agent 文件的 `model: provider/model#variant` 里，由 `install.sh --host opencode --with-agents --model-map 'T0=…,T1=…,…'` 生成（见 `adapters/opencode/README.md`）。**variant 名来自模型目录，不是每个模型都有 `low`/`medium`/`high`**，写了不存在的 variant 会报模型解析错误；可在 `--model-map` 里显式写 `#<variant>` 覆盖。用 `opencode models` 查看可用模型。
- 没设 model 的 `hq-t*` 继承父会话模型，这时五档只是说明不同，台账和 notes 记 `tier:not-applied`。
- **成本系数**（`calibration.md` 规则 9）：按 hq-t* 实际用的 provider 判断计费方。Anthropic 模型按 `high`；OpenAI、DeepSeek 等按 `low`。混用时在 PLAYBOOK 写 `cost_weight`。
- task 记录：`host` 记 `opencode`，`channel` 记 `A`，`model` 记 agent 文件里的 `provider/model#variant`（没设时记 `inherit:<父会话模型>`）。
- 首次运行把最终映射写进 PLAYBOOK“选档偏好”（注明宿主 opencode）。

## 4. 安装与调用

- 安装：`./install.sh --host opencode --with-agents --model-map 'T0=<p/m>,T1=<p/m>,T2=<p/m>,T3=<p/m>,T4=<p/m>'`。技能装到 OpenCode 能读到的目录（单独装时为 `~/.config/opencode/skills`；与 claude/codex 一起装时共用 `~/.claude/skills` 或 `~/.agents/skills`），子代理模板装到 `~/.config/opencode/agents/hq-t*.md`（`--scope project` 时为 `<项目>/.opencode/agents/`）。
- 调用：在 OpenCode 里说“用 hq 技能 + 目标”，或按 OpenCode 的技能触发方式；模型会通过 skill 工具加载 hq。
- 首次运行：
  1. 确认 `hq-t0…hq-t4` 已被识别（在 OpenCode 里问它能派哪些子代理，或查看 agent 列表）；
  2. 确认各档的 `model` 和 variant 能解析（每档派一个只回复 OK 的小任务）；
  3. 把映射写进 `.hq/PLAYBOOK.md`。
- 权限：模板没有写 `permissions`，子代理沿用全局权限。全局把 `edit`、`shell` 设为 `ask` 时，后台子代理的审批会打断用户；需要无人值守时在 OpenCode 配置里为 `hq-t*` 单独放行（由用户决定，安装脚本不改配置）。
- **W 通道**（v0.4.2）：`cli-worker.sh start --cli opencode --model <provider/model> [--effort <variant>] --brief <文件>`，实际运行 `opencode run --model <p/m#variant> --format json --title hq/<id> [--auto|--agent plan]`，简报走 stdin，用量从 `step_finish` 事件逐步相加。需要真正的进程和目录隔离时用它代替子代理（各自在 `.hq/worktrees/<id>` 里运行）。注意 `--auto` 会批准全部未拒绝的权限，比 codex 的 workspace-write 宽。参数依据 V2 源码和帮助，未实机运行。

## 5. 已知限制与待核实项

1. **只读过文档、没有实机运行**，下列各项都可能与实际版本不符。
2. 待核实：中止单个运行中子代理的方式（stop_worker）。
3. 待核实：`opencode session export` 的 JSON 里 token 和成本字段名（worker_usage）。
4. 待核实：并行子代理是否有上限；多个后台子代理同时运行时权限审批的表现。
5. 待核实：常用模型目录里实际有哪些 variant（`low`/`medium`/`high` 是否普遍可用）。
6. 子代理与主会话共用工作目录，隔离只靠说明约束和派发前后 `git status` 检查；越界改动的发生率在复盘里看“问题数”。
7. V1 版本的 OpenCode 不适用本文件（agent 目录、字段、子代理工具名都不同），请升级到 V2 或按 `generic.md` 使用。
