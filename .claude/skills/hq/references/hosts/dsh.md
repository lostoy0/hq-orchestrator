# 宿主适配：DeepSeek Harness（dsh）

## 1. 概述与适用版本

- 适用：DeepSeek Harness（简称 dsh，DeepSeek 官方智能体工具，有桌面端）作为 hq 的**原生宿主**。dsh 原生支持 SKILL.md 技能和子代理，每次派子代理都能指定 provider、model 和思考深度，所以五个档位能逐任务生效。**这是 DeepSeek 的推荐接入路径**（其他路径见 [deepseek.md](deepseek.md)）。
- 核实状态（2026-11-25）：**只读了官方仓库 deepseek-ai/deepseek-harness 提交 4b399c3（2026-11-22）的文档，没有安装、没有实机运行**。来源：`docs/subsystems/skills.md`、`docs/subsystems/subagent.md`、`packages/subagent/tool-subagent/README`、`docs/subsystems/schedule.md`。适用的 dsh 版本：待核实。
- **技能发现**（按优先级，数字小者优先）：`<项目>/.dsh/skills`(100) > `<项目>/.agents/skills`(200) > 自定义目录(300) > `<dshHome>/skills`(400) > `<agentsHome>/skills`(500) > 随包目录(600)。dshHome 默认 `$DSH_HOME` 或 `~/.dsh`；agentsHome 默认 `$DSH_AGENTS_HOME` 或 `~/.agents`；项目根是包含 `.git` 的最近祖先目录。技能名须为 kebab-case；支持 `<name>/SKILL.md` 目录形式；**不支持嵌套递归发现**；目录中 description 默认最多 500 字符。因此**装到 `~/.agents/skills`（Codex 的目录）后 dsh 也能读到**，不必重复安装。
- **识别特征**：工具列表里有 `subagent`、`list_subagent_models`、`list_agents`；或存在 `~/.dsh/`、环境变量 `$DSH_HOME`。

## 2. 能力表

| 能力 | 怎么做 | 不支持时的降级 |
|---|---|---|
| spawn_worker | `subagent` 工具（后端为进程内 spawn），传 `provider`、`model`、`reasoning_effort`（`provider` 和 `model` 必须一起给；`reasoning_effort` 必须和这两个一起出现），可选 `name`、`agent_preset`。调用后立即返回 `started subagent <name>`，不等结果。**首次运行先调用 `list_subagent_models`**，把档位映射写进 PLAYBOOK“选档偏好”（注明宿主 dsh）。需开启 `modelSelection`：文档称 Web 和 Desktop 预设已为 spawn 开启，并提供 `list_subagent_models` | 路由未授权报 `MODEL_ROUTE_NOT_ALLOWED`：先调 `list_subagent_models`，只用返回的路由；设置关闭时只能用父代理当前的 provider/model，档位只靠思考深度区分，台账备注写明 |
| monitor | 子代理完成时 dsh 会通知父代理；另用 `list_agents` 看子代理树（状态 running / inactive，**不代表任务是否完成**，以完成通知和交付内容为准） | 等完成通知，交付格式里写清结果 |
| message_worker | `send_message`，给子代理树里的成员发消息（纠偏、回答 CHECKPOINT） | 停掉后带补充信息重新派 |
| stop_worker | 待核实（文档里没有找到明确的中止工具） | 等它自然结束，不合并其结果 |
| worker_usage | 待核实：子代理用量和成本的读取方式未在已读文档中找到。tokens 口径同 runtimes.md（input + output + cache_write，不含 cache_read） | 拿不到就 tokens、cost_usd 都填 null，不估算；以 DeepSeek 控制台账单为准，`flags` 记 `billing:deepseek` |
| schedule_checkin | dsh 的 Schedule（宿主级持久定时任务，时间类型 after、at、every、daily、weekly、cron、rrule；目标可复用已有 Session、新建 Session 或每次投递）。用“after/every + 复用当前 Session”做兜底巡检。面向模型的具体工具名：待核实 | 主会话在等待期间定期 `list_agents` |
| remote_workers | 无云端子会话。外部后端（ACP、Codex、Claude Code）**不支持选择模型**（挂载会失败），只能做跨厂商的一次性任务，且需 PLAYBOOK `worker_clis` 授权 | 只用本地 `subagent` |
| local_machine | 不适用：dsh 本来就在本地运行 | — |
| concurrency_limit | 子代理树容量（`list_agents` 可看并发容量，嵌套深度受 maxDepth 限制；配置键待核实）。并发数取它与 `resources.sh` 算出的槽位的**较小值** | 读不到容量时按 resources.sh 槽位 |

## 3. 档位映射 T0–T4 →（模型, 思考深度）

**额度成本偏好**：本宿主按 `calibration.md` 规则 9 属于低成本（`cost_weight: low`），难度拿不准时上调一整档；关键路径上的小任务不上调，遇到限流先降并发、不撤销上调（规则 11），上调的任务在 `flags` 记 `bias:+1(tier)`。

DeepSeek 只有 pro 和 flash 两档，五档合成两档，靠思考深度区分。下表 provider/model 名只是示意（直连 API 名为 deepseek-v4-flash / deepseek-v4-pro），**以 `list_subagent_models` 返回为准**，首次运行写进 PLAYBOOK。

| 档位 | 模型 | reasoning_effort |
|---|---|---|
| T0 | flash | low |
| T1 | flash | low |
| T2 | flash | medium |
| T3 | pro | medium |
| T4 | pro | high |

- 思考深度的取值范围待核实；`list_subagent_models` 会列出各模型支持的深度，不支持 `high` 时 T4 用支持的最高一级（不含仅在用户要求时用的 `max`）。
- task 记录：`host` 记 `dsh`，`channel` 记 `A`，`model` 记 `list_subagent_models` 返回的 `<provider>/<model>`。

## 4. 安装与调用

- 安装：`./install.sh --host dsh`（个人范围装到 `${DSH_HOME:-~/.dsh}/skills`；`--scope project` 装到 `<项目>/.dsh/skills`）。已用 `--host codex` 装到 `~/.agents/skills` 的，dsh 也能读到，不必重复安装。
- 调用：在 dsh（桌面端或其他前端）里调用 hq 技能（具体触发方式，如 `/hq`，待核实）。
- 首次运行：
  1. 在桌面端开启子代理模型选择（设置位置待核实，文档提到 `/model-selection-settings`）；
  2. 调用 `list_subagent_models`，按上表把 T0–T4 映射到返回的路由，写进 `.hq/PLAYBOOK.md`“选档偏好”；
  3. 跑一个 T0 和一个 T3 小任务，核对实际用的模型和深度。
- **W 通道暂不接入**：dsh 的非交互 CLI 命令待核实，`cli-worker.sh` 没有 dsh 分支。dsh 宿主下派发只用 `subagent`；需要 W 时只能用已支持的 `codex` / `claude`（跨厂商，需 `worker_clis` 授权）。

## 5. 已知限制与待核实项

1. **只读过文档、没有实机运行**（提交 4b399c3），以下各项都可能与实际版本不符。
2. 待核实：桌面端子代理模型路由设置在界面的哪个位置。
3. 待核实：子代理并发上限的配置键。
4. 待核实：dsh 的非交互 CLI 命令（能否作为 W 通道的 worker）。
5. 待核实：`reasoning_effort` 的取值范围。
6. 待核实：子代理用量和成本的读取方式（暂填 null）。
7. 待核实：中止子代理的方式（stop_worker）；Schedule 面向模型的工具名；技能的调用方式。
8. 外部后端（ACP、Codex、Claude Code）不能选择模型，档位在这些后端上不生效。
9. flash 承担 T0–T2，复盘看这三档与 T3/T4 的一次通过率差异。
