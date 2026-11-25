# 宿主适配：通用（Cursor、Gemini CLI 及其他支持 SKILL.md 的工具）

## 1. 概述与适用范围

- 适用：还没有专门宿主文档的工具。v0.4.0 起 `install.sh` 能把技能装到 Cursor、Gemini CLI 读取的目录（见 `adapters/hosts.tsv`，级别 `basic`），这些工具在 hq 里统一按本文件运行。**OpenCode 自 v0.4.1 起有专门文档 `opencode.md`**；版本为 V1 或没装 `hq-t*` 子代理时也可按本文件降级运行。
- 核实状态（2026-11-25）：技能目录来自各工具官方文档，**没有实机运行**。各工具的原生子代理（Cursor `.cursor/agents/`、Gemini CLI `.gemini/agents/`）**暂不使用**，等专门的宿主文档核实后再接（计划见 `docs/design-more-hosts.md`）。
- **识别特征**（任一即可；结果写进台账头部，`host` 记对应 id）：

| host | 特征 |
|---|---|
| `opencode` | 见 `opencode.md`；只在它无法使用时（V1 版本、没装 `hq-t*`）按本文件降级 |
| `cursor` | 系统提示表明是 Cursor Agent；有 `.cursor/` 或 `~/.cursor/` |
| `gemini` | 系统提示表明是 Gemini CLI；有 `.gemini/` 或 `~/.gemini/` |
| `other` | 都不符合 |

## 2. 能力表

| 能力 | 怎么做 | 不支持时的降级 |
|---|---|---|
| spawn_worker | 有 shell 且 PLAYBOOK `worker_clis` 允许时，用 W 通道：`cli-worker.sh start --cli codex|claude ...`（需要本机装了对应 CLI） | 降级模式：主会话按同样的计划**串行**亲自执行，channel 记 `main` |
| monitor | W：`cli-worker.sh status --id <id>` / `list` | 降级模式下不需要 |
| message_worker | 不支持 | W 任务 `stop` 后带补充信息重新 `start` |
| stop_worker | W：`cli-worker.sh stop --id <id>` | — |
| worker_usage | W：`cli-worker.sh usage --id <id>`；主会话自身用量通常拿不到 | 填 null，不估算 |
| schedule_checkin | 不支持 | 等待期间定期 `cli-worker.sh list` |
| remote_workers | 不支持 | — |
| local_machine | 不适用：这些工具在本地运行 | — |
| concurrency_limit | 只用 `resources.sh` 算出的本地槽位 | — |

## 3. 档位映射

- 降级模式下档位**不改变模型**：主会话用的就是当前模型，task 的 `tier` 照常按 `calibration.md` 打分记录（复盘用来对照难度和返工），`model` 记当前模型名（不知道就记 `unknown`），notes 写 `tier:not-applied`。
- W 通道的任务按目标 CLI 的映射选模型：`claude` 见 `hosts/claude-code.md` 第 3 节，`codex` 见 `hosts/codex.md` 第 3 节；model 记成 `<cli>:<模型名>`。
- 成本系数（`calibration.md` 规则 9）：按实际计费方在 PLAYBOOK 写 `cost_weight`；没写时按 `high` 处理（不上调）。

## 4. 安装与调用

- 一键安装：`./install.sh --host auto`（自动检测）或 `--host opencode,cursor,gemini`。默认的最小目录布局下，OpenCode 和 Gemini CLI 通常从 `~/.agents/skills` 读到，Cursor 从 `~/.claude/skills` 读到；`./install.sh --list` 可以先看计划。
- 也可用社区通用安装器：`npx skills add lostoy0/hq-orchestrator -a opencode -a cursor -a gemini-cli`（是否完整复制 `scripts/`、`references/` 待核实；缺了脚本时资源检测和 W 通道不可用）。
- 调用：在会话里说“用 hq 技能 + 目标”，或按该工具的技能触发方式。Gemini CLI 首次激活技能需要用户同意。
- 脚本路径：先读 `~/.hq/skill-path`（安装脚本写入的 hq 目录），再按 SKILL.md 第 1 步的 find 路径找。

## 5. 已知限制与待核实项

1. 只装了技能，档位不生效；大目标在降级模式下是串行的，用时会明显长于原生宿主。
2. OpenCode 已在 v0.4.1 升级为原生宿主（见 `opencode.md`）。
3. 待核实：Cursor 子代理的文件格式、能否指定模型；`agent -p` 的 `--model` 参数（团队管理员可禁用 headless）。
4. 待核实：Gemini CLI 子代理模型只能在 `settings.json` 的 `agents.overrides` 设置；`gemini -p -m <model> --output-format json` 作为 W 后端。
5. 待核实：Cursor 是否读取 `~/.agents/skills`（登记表暂未计入，Cursor 按 `~/.claude/skills` 覆盖）。
