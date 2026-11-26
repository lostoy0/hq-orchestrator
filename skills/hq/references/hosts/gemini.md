# 宿主适配：Gemini CLI

## 1. 概述与适用版本

- 适用：Gemini CLI 作为 hq 的**原生宿主**。Gemini CLI 的自定义子代理可以在定义文件里设 `model`，给 T0–T4 各建一个子代理 `hq-t0…hq-t4`，档位就能逐任务生效（只靠模型区分，没有思考深度设置）。
- 核实状态（2026-11-25）：**只读了官方文档**（GitHub `google-gemini/gemini-cli` 的 `docs/core/subagents.md`、`docs/cli/skills.md`、`docs/extensions/reference.md`、`docs/cli/custom-commands.md`、`docs/cli/headless.md`、`docs/cli/cli-reference.md`，2026-11-24 的提交），**没有安装、没有实机运行**。官方把子代理标为预览功能，可能变化。
- **技能发现**（优先级由低到高）：内置 < 扩展 < 用户（`~/.gemini/skills`，别名 `~/.agents/skills`）< 工作区（`.gemini/skills`，别名 `.agents/skills`）；同一层里 `.agents/skills` 优先。同名技能用优先级高的。模型通过 `activate_skill` 工具激活技能，**用户要在界面上同意**，之后技能目录加入可读路径。
- **识别特征**：系统提示表明是 Gemini CLI；工具列表里有 `activate_skill`、`run_shell_command`、`read_file` 等；存在 `.gemini/` 或 `~/.gemini/`。

## 2. 能力表

| 能力 | 怎么做 | 不支持时的降级 |
|---|---|---|
| spawn_worker | 子代理以**同名工具**出现：调用 `hq-t0`…`hq-t4`（按档位），参数里给完整任务说明。子代理在独立上下文里运行，不能再派子代理。**调用会等子代理完成才返回**（文档未写后台运行）；同一轮里发起多个子代理调用能否并行，待核实。首次运行先确认 `hq-t*` 存在（`/agents` 列表），不存在时用内置 `generalist`（档位不生效，notes 记 `tier:not-applied`）。需要真正的并行或进程隔离时改用 W：`cli-worker.sh start --cli gemini --model <m> ...`（宿主自己的 CLI，不需 `worker_clis` 授权） | W 通道或降级模式（见 `generic.md`） |
| monitor | 子代理调用返回即完成；W 用 `cli-worker.sh status` / `list` | — |
| message_worker | 不支持向运行中的子代理发消息 | 子代理遇到检查点提前返回，主会话处理后再派一个接着做 |
| stop_worker | 子代理受 `max_turns`、`timeout_mins` 限制（模板为 100 轮、60 分钟）；中途中止只能由用户在界面上取消。W：`cli-worker.sh stop` | 等它结束，不合并其结果 |
| worker_usage | 子代理：文档未给出用量读取方式，填 null。W：`cli-worker.sh usage`（`result.stats` 的 input_tokens − cached + output_tokens） | null，不估算 |
| schedule_checkin | 不支持 | 子代理是同步的，不需要；W 任务在主会话每回合 `cli-worker.sh list` |
| remote_workers | 不支持（远程 A2A 子代理不在本适配范围） | — |
| local_machine | 不适用：在本地运行 | — |
| concurrency_limit | 子代理：按同步执行处理，一次一个（并行待核实）；W：按 `resources.sh` 槽位 | — |

### 隔离（重要）

子代理和主会话在同一个工作区里，没有 worktree 参数。做法同 `opencode.md`：改代码的任务由主会话先 `git worktree add .hq/worktrees/<id> -b hq/<id> <基线>`，任务说明第一行写 `工作目录: <绝对路径>`（模板已要求子代理只在该目录内读写）；派发前后检查主工作区 `git status --porcelain` 不变。worktree 在工作区目录之内，子代理能直接访问。

## 3. 档位映射

| 档位 | 子代理 | 模型档次 | 说明 |
|---|---|---|---|
| T0 | hq-t0 | 最快的小模型 | 如 flash-lite 档 |
| T1 | hq-t1 | 快速的中档模型 | 如 flash 档 |
| T2 | hq-t2 | 中档模型 | 如 flash 档 |
| T3 | hq-t3 | 最强模型 | 如 pro 档 |
| T4 | hq-t4 | 最强模型 | 如 pro 档 |

- 具体模型名以你账户在 Gemini CLI 里可选的为准（`/model`），不要凭记忆填。用 `install.sh --host gemini --with-agents --model-map 'T0=…,…,T4=…'` 写进模板，或在 `settings.json` 的 `agents.overrides.<hq-tN>.modelConfig.model` 里覆盖（见 `adapters/gemini/README.md`）。
- **没有思考深度**：T3 和 T4 用同一个模型时差别只在任务说明和尝试次数；复盘时比较 T3/T4 一次通过率，判断要不要给 T4 换更强的模型。
- **成本系数**（`calibration.md` 规则 9）：按实际计费方判断，默认按 `low`（与 Codex、DeepSeek 同类的额度型计费）；用付费 API 密钥按量计费时可在 PLAYBOOK 写 `cost_weight: high`。
- task 记录：`host` 记 `gemini`，子代理的 `channel` 记 `A`，`model` 记模板里的模型名（没设时记 `inherit:<主会话模型>`）；W 任务 `channel` 记 `W`，`model` 记 `gemini:<模型名>`。
- 首次运行把最终映射写进 PLAYBOOK“选档偏好”（注明宿主 gemini）。

## 4. 安装与调用

- **扩展**（提供 `/hq`、`/hq-retro` 和 `/hq-research`、`/hq-prd`、`/hq-design`、`/hq-arch`、`/hq-plan`、`/hq-blueprint`、`/hq-launch` 命令）：`gemini extensions install https://github.com/lostoy0/hq-orchestrator --ref <版本标签>`；子代理模板再用 `./install.sh --host gemini --with-agents --model-map …` 单独装（扩展里不带子代理，原因见 `adapters/gemini/README.md`）。
- **install.sh**：`./install.sh --host gemini --with-agents --model-map …`，技能装到 `~/.gemini/skills`（与其他工具一起装时为 `~/.agents/skills`），子代理装到 `~/.gemini/agents/`（`--scope project` 时为 `<项目>/.gemini/agents/`）。没有 `/hq` 命令，在会话里说“用 hq 技能 + 目标”。
- 两种都装时用户目录的技能覆盖扩展里的，建议只留一种。
- 首次运行：
  1. 同意激活 hq 技能；
  2. `/agents` 确认 `hq-t0…hq-t4` 已加载、模型正确；
  3. 每档派一个只回复 OK 的小任务；
  4. 把映射写进 `.hq/PLAYBOOK.md`。
- 脚本路径：先读 `~/.hq/skill-path`（install.sh 写入），扩展安装时在 `~/.gemini/extensions/hq-orchestrator/skills/hq/`。

## 5. 已知限制与待核实项

1. **只读过文档、没有实机运行**；子代理是预览功能。
2. 待核实：同一轮里多个子代理调用能否并行。
3. 待核实：子代理的用量读取方式（暂填 null）。
4. 待核实：扩展命令里 `activate_skill` 的提示能否让模型稳定激活 hq 技能。
5. 子代理同步执行、不能续发消息，检查点只能靠“提前返回 + 再派一个”。
6. 子代理与主会话共用工作区，隔离只靠说明约束和派发前后 `git status` 检查。
7. W 通道的 `auto_edit` 下 shell 命令可能不可用（见 `runtimes.md` W 节）。
