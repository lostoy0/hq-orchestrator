# 宿主适配：OpenAI Codex

## 1. 概述与适用版本

- 适用：Codex CLI（目标版本 0.172.0）作为 hq 的宿主，另可用 W 通道启动 `codex exec` 子进程。
- 核实状态（2026-11-25，本环境装不了 codex，没有实机运行）：
  - **已按官方文档核对**（限定官方域名的搜索摘要）：自定义 agent 放在 `~/.codex/agents/`（个人）或 `<项目>/.codex/agents/`（项目），每个文件一个 agent，必填 `name`、`description`、`developer_instructions`，可选 `model`、`model_reasoning_effort`、`model_reasoning_summary`、`model_verbosity`；文件里的值优先，只设 model 时沿用之前解析出的 effort；`sandbox_mode`、`approval_policy`、`model_provider`、`mcp_servers` 写在 agent 文件里不覆盖父会话；缺 `developer_instructions` 的文件据报被忽略，`instructions`、`reasoning_effort` 键不生效。技能目录：个人 `~/.agents/skills/`，仓库 `.agents/skills/`。`codex exec` 不传提示词或传 `-` 时从 stdin 读到 EOF 再执行；`--json` 逐行输出 JSON 事件，`turn.completed` 带 usage（input_tokens 含 cached_input_tokens，output_tokens 含 reasoning_output_tokens，值为线程累计）。
  - **仍待核实**：`-m`、`-c key=value`、`-s` 的确切写法；并发上限 `agents.max_concurrent_threads_per_session`（旧名 `agents.max_threads`）；`codex cloud exec` 不支持指定 model 和 effort 的 issue。
- 本文件涉及的 claude 参数（W 通道用）已用 `claude --help`（2.1.331）核实：`-p/--print`、`--model`、`--output-format stream-json`、`--effort`、`--verbose`、`--permission-mode`。

## 2. 能力表

| 能力 | 怎么做 | 不支持时的降级 |
|---|---|---|
| spawn_worker | 优先 Codex 原生子代理：按档位选 `hq-tN` agent，可并行。其次 W 通道：`cli-worker.sh start --cli codex --model <m> --effort <e> --brief <文件>`，模型和深度逐任务指定 | 都不可用则降级为主会话串行亲自执行 |
| monitor | 原生子代理：用 Codex 自带的线程/子代理状态查看（具体命令待核实）。W 通道：`cli-worker.sh status --id <id>`，输出 `out.jsonl` 看进度 | 主会话定期 `cli-worker.sh list` |
| message_worker | 原生子代理：向运行中的子代理补充信息的方式待核实。W 通道不支持 | `stop` 后带补充信息重新 `start`（新 id）|
| stop_worker | 原生：由主线程中止子代理（待核实）。W 通道：`cli-worker.sh stop --id <id>`（TERM，10 秒后 KILL，worktree 保留）| 等它自然结束，不合并其结果 |
| worker_usage | W 通道：`cli-worker.sh usage --id <id>`，解析 `out.jsonl` 里 `turn.completed` 的 usage；tokens = input + output + cache_write，不含 cache_read（codex 的 `input_tokens` 含 cached，脚本已扣除；output 已含 reasoning，不重复加；usage 是线程累计值，单次 exec 取最后一条）；cost_usd 一般拿不到。原生子代理的用量取法待核实 | 拿不到填 null，不估算 |
| schedule_checkin | Codex 很可能没有定时唤醒能力（待核实）| 主会话在等待期间定期运行 `cli-worker.sh list` |
| remote_workers | `codex cloud`（待核实）。已有 issue 报告 `codex cloud exec` 不支持指定 model 和 effort，档位可能不生效 | 用 W 通道在本机跑，或主会话串行 |
| local_machine | 不适用：Codex CLI 本来就在本地运行 | — |
| concurrency_limit | `agents.max_concurrent_threads_per_session`（旧名 `agents.max_threads`）。并发数取它与 `resources.sh` 算出的槽位的较小值 | 无法读取配置时按 resources.sh 槽位 |

## 3. 档位映射

**额度成本偏好**：本宿主按 `calibration.md` 规则 9 属于低成本（`cost_weight: low`），难度拿不准时上调一档；关键路径上的小任务或遇到限流时不上调，上调的任务在 notes 记 `bias:+1(cost_low)`。

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
- agent 模板：复制 `adapters/codex/agents/hq-t*.toml` 到 `~/.codex/agents/`（个人）或 `<项目>/.codex/agents/`（项目），或用 `./install.sh --host codex --with-agents`（按 `--scope` 自动选目录；旧写法 `--with-codex-agents` 仍可用）；然后替换模型占位符，见 `adapters/codex/README.md`。也可以安装时直接填模型：`--with-agents --model-map 'T0=<模型>,…,T4=<模型>'`（思考深度按档位写入）。
- W 通道：`bash skills/hq/scripts/cli-worker.sh start --id t2 --cli codex --model <m> --brief <文件>`；简报经 stdin 传入。sandbox 默认 `workspace-write`；`danger-full-access` 必须另加 `--allow-dangerous`，否则拒绝（退出码 2）。

## 5. 已知限制与待核实项

1. `codex exec` 的 `-m`、`-c model_reasoning_effort=`、`-s` 未经 `codex exec --help` 核对（`--json`、`-` 读 stdin 已按官方文档核对）；cli-worker.sh 的 codex 分支只在假 CLI 上测过。
2. agent TOML 的字段名和放置目录已按官方文档核对，未实机运行。
3. usage 字段名已按官方文档核对；恢复会话（`exec resume`）时 usage 是累计值，cli-worker.sh 不处理 resume，用到时需自行做差。
4. 原生子代理的监控、补充信息、中止、用量取法待核实。
5. 是否有定时唤醒能力待核实，暂按没有处理。
6. `codex cloud` 的 model/effort 可能不生效；`xhigh` 是否支持待核实。
7. W 通道 sandbox 默认 workspace-write；worktree 在仓库内 `.hq/worktrees/`，沙箱能否写主仓库 `.git`（提交需要）待核实。
8. 旧名 `agents.max_threads` 与新名并存的行为待核实。
