# 宿主适配：OpenAI Codex

## 1. 概述与适用版本

- 适用：Codex CLI（目标版本 0.172.0）作为 hq 的宿主，另可用 W 通道启动 `codex exec` 子进程。
- 核实状态：**以下内容尚未用 CLI help 核实**（2026-11-25，本环境安装 codex 被拒绝，没能看 `codex --help`）。来源是任务说明转述的、限定官方域名的搜索摘要：Codex 支持 SKILL.md；子代理在自定义 agent 的 TOML 里设 `model`、`model_reasoning_effort`，不设则继承父会话；并发上限 `agents.max_concurrent_threads_per_session`（旧名 `agents.max_threads`）；`codex exec` 有 `-m`、`-c key=value`、`-s`、`--json`；有 issue 报告 `codex cloud exec` 不支持指定 model 和 effort。以上都待核实。
- 本文件涉及的 claude 参数（W 通道用）已用 `claude --help`（2.1.331）核实：`-p/--print`、`--model`、`--output-format stream-json`、`--effort`、`--verbose`、`--permission-mode`。

## 2. 能力表

| 能力 | 怎么做 | 不支持时的降级 |
|---|---|---|
| spawn_worker | 优先 Codex 原生子代理：按档位选 `hq-tN` agent，可并行。其次 W 通道：`cli-worker.sh start --cli codex --model <m> --effort <e> --brief <文件>`，模型和深度逐任务指定 | 都不可用则降级为主会话串行亲自执行 |
| monitor | 原生子代理：用 Codex 自带的线程/子代理状态查看（具体命令待核实）。W 通道：`cli-worker.sh status --id <id>`，输出 `out.jsonl` 看进度 | 主会话定期 `cli-worker.sh list` |
| message_worker | 原生子代理：向运行中的子代理补充信息的方式待核实。W 通道不支持 | `stop` 后带补充信息重新 `start`（新 id）|
| stop_worker | 原生：由主线程中止子代理（待核实）。W 通道：`cli-worker.sh stop --id <id>`（TERM，10 秒后 KILL，worktree 保留）| 等它自然结束，不合并其结果 |
| worker_usage | W 通道：`cli-worker.sh usage --id <id>`，解析 `out.jsonl` 的 usage；tokens = input + output + cache_write，不含 cache_read（codex 的 `input_tokens` 含 cached，脚本已扣除）；cost_usd 一般拿不到。原生子代理的用量取法待核实 | 拿不到填 null，不估算 |
| schedule_checkin | Codex 很可能没有定时唤醒能力（待核实）| 主会话在等待期间定期运行 `cli-worker.sh list` |
| remote_workers | `codex cloud`（待核实）。已有 issue 报告 `codex cloud exec` 不支持指定 model 和 effort，档位可能不生效 | 用 W 通道在本机跑，或主会话串行 |
| local_machine | 不适用：Codex CLI 本来就在本地运行 | — |
| concurrency_limit | `agents.max_concurrent_threads_per_session`（旧名 `agents.max_threads`）。并发数取它与 `resources.sh` 算出的槽位的较小值 | 无法读取配置时按 resources.sh 槽位 |

## 3. 档位映射

具体型号以 `codex` 可用模型为准，首次运行时写进 PLAYBOOK；不要凭记忆填。

| 档位 | 模型档次 | reasoning effort |
|---|---|---|
| T0 | 最快的小模型 | low |
| T1 | 快速的中档模型 | low |
| T2 | 中档模型 | medium |
| T3 | 最强模型 | medium |
| T4 | 最强模型 | high（必要时 xhigh，待核实是否支持） |

跨厂商记录：task 的 `model` 写成 `codex:<模型名>`。

## 4. 安装与调用

- 技能：复制 `skills/hq/` 到 `~/.agents/skills/hq`（个人）或仓库 `.agents/skills/hq`。
- agent 模板：复制 `adapters/codex/agents/hq-t*.toml` 到官方规定目录（预计 `~/.codex/agents/` 或 `.codex/agents/`，待核实），并替换模型占位符，见 `adapters/codex/README.md`。
- W 通道：`bash skills/hq/scripts/cli-worker.sh start --id t2 --cli codex --model <m> --brief <文件>`；简报经 stdin 传入。

## 5. 已知限制与待核实项

1. codex 的全部参数（`exec`、`-m`、`-c model_reasoning_effort=`、`-s`、`--json`、PROMPT 为 `-` 时读 stdin）未经 help 核实，cli-worker.sh 的 codex 分支按此编写，只在假 CLI 上测过。
2. agent TOML 的字段名和放置目录待核实。
3. codex `--json` 事件里 usage 的字段名（脚本按 `usage.input_tokens/cached_input_tokens/output_tokens` 解析）待核实；解析不到就是 null。
4. 原生子代理的监控、补充信息、中止、用量取法待核实。
5. 是否有定时唤醒能力待核实，暂按没有处理。
6. `codex cloud` 的 model/effort 可能不生效；`xhigh` 是否支持待核实。
7. W 通道 sandbox 默认 workspace-write；worktree 在仓库内 `.hq/worktrees/`，沙箱能否写主仓库 `.git`（提交需要）待核实。
8. 旧名 `agents.max_threads` 与新名并存的行为待核实。
