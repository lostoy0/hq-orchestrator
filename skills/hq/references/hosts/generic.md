# 宿主适配：通用（Cursor 及其他支持 SKILL.md 的工具）

## 1. 概述与适用范围

- 适用：还没有专门宿主文档的工具。v0.4.0 起 `install.sh` 能把技能装到 Cursor 等工具读取的目录（见 `adapters/hosts.tsv`，级别 `basic`），这些工具在 hq 里统一按本文件运行。**OpenCode（v0.4.1 起）和 Gemini CLI（v0.4.3 起）有专门文档 `opencode.md`、`gemini.md`**；它们没装 `hq-t*` 子代理（或 OpenCode 为 V1）时也可按本文件降级运行。
- 核实状态（2026-11-25）：技能目录来自各工具官方文档，**没有实机运行**。各工具的原生子代理（Cursor `.cursor/agents/`）**暂不使用**，等专门的宿主文档核实后再接（计划见 `docs/design-more-hosts.md`）。
- **识别特征**（任一即可；结果写进台账头部，`host` 记对应 id）：

| host | 特征 |
|---|---|
| `opencode` | 见 `opencode.md`；只在它无法使用时（V1 版本、没装 `hq-t*`）按本文件降级 |
| `cursor` | 系统提示表明是 Cursor Agent；有 `.cursor/` 或 `~/.cursor/` |
| `gemini` | 见 `gemini.md`；只在没装 `hq-t*` 子代理时按本文件降级（W 通道用 `--cli gemini`） |
| `other` | 都不符合 |

## 2. 能力表

| 能力 | 怎么做 | 不支持时的降级 |
|---|---|---|
| spawn_worker | 有 shell 时用 W 通道。**优先用宿主自己的 CLI**（不需要 `worker_clis` 授权）：Cursor 宿主用 `cli-worker.sh start --cli cursor --model <m> ...`（Gemini CLI 降级时用 `--cli gemini`）；能按任务指定模型，档位因此生效。其他 CLI（codex、claude、opencode）属跨厂商，需 `worker_clis` 授权 | 降级模式：主会话按同样的计划**串行**亲自执行，channel 记 `main` |
| monitor | W：`cli-worker.sh status --id <id>` / `list` | 降级模式下不需要 |
| message_worker | 不支持 | W 任务 `stop` 后带补充信息重新 `start` |
| stop_worker | W：`cli-worker.sh stop --id <id>` | — |
| worker_usage | W：`cli-worker.sh usage --id <id>`；主会话自身用量通常拿不到 | 填 null，不估算 |
| schedule_checkin | 不支持 | 等待期间定期 `cli-worker.sh list` |
| remote_workers | 不支持 | — |
| local_machine | 不适用：这些工具在本地运行 | — |
| concurrency_limit | 只用 `resources.sh` 算出的本地槽位 | — |

## 3. 档位映射

- 用 W 通道跑宿主自己的 CLI 时，档位按 `--model` 生效（Gemini、Cursor 命令行不支持思考深度，只能靠模型区分档位）；task 的 `channel` 记 `W`，`model` 记 `<cli>:<模型名>`。
- 降级模式下档位**不改变模型**：主会话用的就是当前模型，task 的 `tier` 照常按 `calibration.md` 打分记录（复盘用来对照难度和返工），`model` 记当前模型名（不知道就记 `unknown`），`flags` 写 `tier:not-applied`。
- W 通道的任务按目标 CLI 的映射选模型：`claude` 见 `hosts/claude-code.md` 第 3 节，`codex` 见 `hosts/codex.md` 第 3 节；model 记成 `<cli>:<模型名>`。
- 成本系数（`calibration.md` 规则 9）：按实际计费方在 PLAYBOOK 写 `cost_weight`；没写时按 `high` 处理（拿不准时默认只上调思考深度一级，模糊度 ≥1 或风险 2 时上调一整档）。

## 4. 安装与调用

- 一键安装：`./install.sh --host auto`（自动检测）或 `--host opencode,cursor,gemini`。默认的最小目录布局下，OpenCode 和 Gemini CLI 通常从 `~/.agents/skills` 读到，Cursor 从 `~/.claude/skills` 读到；`./install.sh --list` 可以先看计划。
- 也可用社区通用安装器：`npx skills add lostoy0/hq-orchestrator -a opencode -a cursor -a gemini-cli`（是否完整复制 `scripts/`、`references/` 待核实；缺了脚本时资源检测和 W 通道不可用）。
- 调用：在会话里说“用 hq 技能 + 目标”，或按该工具的技能触发方式。Gemini CLI 首次激活技能需要用户同意。
- 脚本路径：先读 `~/.hq/skill-path`（安装脚本写入的 hq 目录），再按 SKILL.md 第 1 步的 find 路径找。

## 5. 已知限制与待核实项

1. 只装了技能，档位不生效；大目标在降级模式下是串行的，用时会明显长于原生宿主。
2. OpenCode（v0.4.1）、Gemini CLI（v0.4.3）已升级为原生宿主（见 `opencode.md`、`gemini.md`）。
3. 待核实：Cursor 子代理的文件格式、能否指定模型；`agent -p` 的 `--model` 参数（团队管理员可禁用 headless）。
4. Gemini CLI 的子代理已确认可在定义文件里设 `model`（官方文档），见 `gemini.md`。
5. 待核实：Cursor 是否读取 `~/.agents/skills`（登记表暂未计入，Cursor 按 `~/.claude/skills` 覆盖）。
