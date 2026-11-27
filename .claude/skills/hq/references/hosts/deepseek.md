# 宿主适配：DeepSeek（宿主 + DeepSeek 后端）

## 1. 概述与适用版本

DeepSeek 是模型，不是宿主。使用方式有三条路径：

- **路径一（推荐）：DeepSeek Harness（dsh）。** DeepSeek 官方智能体工具，作为 hq 的原生宿主，每次派子代理都能指定模型和思考深度。完整说明见 [dsh.md](dsh.md)（只读过文档、未实机运行）。本文件以下内容只针对路径二、三。
- **路径二：Claude Code 接 DeepSeek。** 能力与 [claude-code.md](claude-code.md) 相同。例外是 B 通道（claude.ai 云端子会话）不在 DeepSeek 后端上运行，用的是 Claude 模型和你的 Claude 套餐额度。
- **路径三：Codex 接 DeepSeek。** 能力与 [codex.md](codex.md) 相同。

核实日期：2026-11-25。来源：api-docs.deepseek.com 的 Anthropic API 指南、Claude Code 接入指南、“Integrate with Codex”页（均经搜索摘要核实，未直接抓取全文）。适用的 Claude Code / Codex 版本：待核实（Codex 官方脚本要求 0.164 及以上，来自搜索摘要，待核实）。

## 2. 能力表

能力沿用所选宿主，下表只写与 DeepSeek 后端相关的差异（路径一 dsh 的能力表见 dsh.md）。

| 能力 | 怎么做 | 不支持时的降级 |
|---|---|---|
| spawn_worker | 路径二：A 通道（`Agent` 工具）；路径三：见 codex.md。B 通道仍是 Claude 模型，不走 DeepSeek | B 不可用或不想用 Claude 额度时改用 A/W |
| monitor | 同所选宿主（claude-code.md / codex.md） | 同宿主文档 |
| message_worker | 同所选宿主 | 同宿主文档 |
| stop_worker | 同所选宿主 | 同宿主文档 |
| worker_usage | cost_usd 优先；tokens = input + output + cache_write，不含 cache_read；拿不到填 null。DeepSeek 后端下 Claude Code 的 cost_usd 按 Claude 价格算，不可信：以 DeepSeek 控制台账单为准，task 记录 `flags` 记 `billing:deepseek` | cost_usd 填 null，tokens 照常 |
| schedule_checkin | 同所选宿主 | 同宿主文档 |
| remote_workers | 路径二：仅 B 通道，且该通道是 Claude 后端；路径三：见 codex.md | 无云端时只用本地 A/W |
| local_machine | 同所选宿主（C 通道依赖云端会话，仅路径二的云端主会话可用） | 主会话直接在本机运行 |
| concurrency_limit | 同所选宿主；DeepSeek 的并发/速率限制待核实 | 先过 resources.sh，保守并发 |

## 3. 档位映射 T0–T4 →（模型, 思考深度）

**额度成本偏好**：DeepSeek 计费的三条路径都按 `calibration.md` 规则 9 属于低成本（`cost_weight: low`），难度拿不准时上调一整档；关键路径上的小任务不上调，遇到限流先降并发、不撤销上调（规则 11），上调的任务在 `flags` 记 `bias:+1(tier)`；但经 Claude Code 派到 claude.ai 云端子会话（B 通道）的任务按 Claude 额度计，仍算 high（拿不准时默认只上调思考深度一级）。

### 路径二：Claude Code

DeepSeek 只有 pro 和 flash 两档，五档合成两档，靠思考深度区分：

| 档位 | 模型别名 | 服务端映射 | 思考深度 |
|---|---|---|---|
| T0 | haiku 或 sonnet | deepseek-flash | low |
| T1 | haiku 或 sonnet | deepseek-flash | low |
| T2 | haiku 或 sonnet | deepseek-flash | medium |
| T3 | opus | deepseek-v4-pro | medium |
| T4 | opus | deepseek-v4-pro | high |

**重点：`CLAUDE_CODE_SUBAGENT_MODEL`。** 官方示例设置了它，它会统一指定所有子代理的模型，可能覆盖插件按档位选的模型，导致所有子代理都用 flash。使用 hq 时**建议不要设置**。如果为了省钱想统一用 flash，要知道 T3/T4 任务有质量风险，复盘时重点看这两档的一次通过率。

**opus 指向。** 官方示例中 `ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-flash[1m]`，opus 也指向 flash。要让 T3/T4 用上 pro，需把它设为 `deepseek-v4-pro`。官方文档确认直连 API 的模型名为 deepseek-v4-pro，且服务端把 claude-opus* 映射到 deepseek-v4-pro；但“该变量可以显式设为 deepseek-v4-pro”这一点官方示例没有直接写出，待核实。

### 路径三：Codex

在 Codex 模型提供方配置里使用 deepseek-v4-flash / deepseek-v4-pro，按 codex.md 的方式映射档位（建议 T0–T2 → flash，T3–T4 → pro，思考深度同上）。Codex 模板文件名与 reasoning 字段以 codex.md 为准。

## 4. 安装与调用

安装技能：路径二、三用 `./install.sh --host claude|codex|all`（见仓库根目录）；路径一用 `--host dsh`，见 dsh.md。调用方式同宿主（Claude Code 用 `/hq`；Codex 见 codex.md）。

### 路径二配置示例（bash）

```bash
export ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic"
export ANTHROPIC_AUTH_TOKEN="<YOUR_DEEPSEEK_API_KEY>"   # 占位符，替换为自己的 key，不要提交到仓库
export ANTHROPIC_DEFAULT_OPUS_MODEL="deepseek-v4-pro"   # 官方示例为 deepseek-flash[1m]；改 pro 见上文，待核实
export ANTHROPIC_DEFAULT_SONNET_MODEL="deepseek-flash"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="deepseek-flash"
export CLAUDE_CODE_EFFORT_LEVEL="max"                   # 官方建议；可能覆盖 hq 按档位设的 effort（待实测），见下文
# 不要设置 CLAUDE_CODE_SUBAGENT_MODEL（原因见第 3 节）
```

变量名 `ANTHROPIC_BASE_URL`、`ANTHROPIC_AUTH_TOKEN` 为 Claude Code 通用写法，DeepSeek 页具体用哪个待核实。

**`CLAUDE_CODE_EFFORT_LEVEL` 与档位的关系（未下结论）**：若它覆盖 A 通道的 `effort` 参数和 W 通道的 `--effort`，第 3 节的思考深度列就不生效，所有档位都按 max 跑（T0–T2 成本上升、用时变长）。设了该变量时，task 记录 `flags` 记 `effort_env:max`；想让档位生效可不设它，再用小任务对比两种设置（见 README 验证清单）。`claude-code.md`、`calibration.md` 已同步标注此风险。

### 路径三配置示例（`~/.codex/config.toml`，依官方“Integrate with Codex”摘要，字段细节待核实）

```toml
model = "deepseek-v4-pro"           # 官方示例默认 deepseek-flash，按需改
model_provider = "deepseek"
model_catalog_json = "~/.codex/models.json"   # 需先按官方页创建模型目录，内含 deepseek-v4-pro 条目

[model_providers.deepseek]
name = "DeepSeek"
base_url = "https://api.deepseek.com/"
wire_api = "responses"
experimental_bearer_token = "<YOUR_DEEPSEEK_API_KEY>"   # 官方示例明文写在配置里；更稳妥的做法待核实
```

官方也提供交互式设置脚本（会备份原 config.toml）。本仓库的 install.sh 不会修改任何配置文件。

## 5. 已知限制与待核实项

- 思考深度在 DeepSeek 上的实际效果：待验证。
- cost_usd 在 DeepSeek 后端下可能不准（Claude Code 按 Claude 价格计算）：以 DeepSeek 控制台账单为准，`flags` 记 `billing:deepseek`。
- B 通道不可用或不走 DeepSeek：用 Claude 模型和 Claude 套餐额度，混用时账单要分开记。
- flash 对 T3/T4 的质量风险：复盘看这两档的一次通过率。
- 待核实：Claude Code 与 Codex 的适用版本；opus 变量设为 deepseek-v4-pro 是否被官方认可；DeepSeek 并发/速率限制；`CLAUDE_CODE_EFFORT_LEVEL` 与 hq 按档位 effort 的关系；Codex 配置字段是否随版本变化；官方示例里 `deepseek-flash` 与 `deepseek-v4-flash` 两个名字是否等价。
