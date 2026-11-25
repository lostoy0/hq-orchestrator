# 宿主适配：DeepSeek（宿主 + DeepSeek 后端）

## 1. 概述与适用版本

DeepSeek 是模型，不是宿主。使用方式是“宿主 + DeepSeek 后端”，分两条路径：

- **路径一：Claude Code 接 DeepSeek。** 能力与 [claude-code.md](claude-code.md) 相同。例外是 B 通道（claude.ai 云端子会话）不在 DeepSeek 后端上运行，用的是 Claude 模型和你的 Claude 套餐额度。
- **路径二：Codex 接 DeepSeek。** 能力与 [codex.md](codex.md) 相同。

核实日期：2026-11-25。来源：api-docs.deepseek.com 的 Anthropic API 指南、Claude Code 接入指南、“Integrate with Codex”页（均经搜索摘要核实，未直接抓取全文）。适用的 Claude Code / Codex 版本：待核实（Codex 官方脚本要求 0.164 及以上，来自搜索摘要，待核实）。

## 2. 能力表

能力沿用所选宿主，下表只写与 DeepSeek 后端相关的差异。

| 能力 | 怎么做 | 不支持时的降级 |
|---|---|---|
| spawn_worker | 路径一：A 通道（`Agent` 工具）；路径二：见 codex.md。B 通道仍是 Claude 模型，不走 DeepSeek | B 不可用或不想用 Claude 额度时改用 A/W |
| monitor | 同所选宿主（claude-code.md / codex.md） | 同宿主文档 |
| message_worker | 同所选宿主 | 同宿主文档 |
| stop_worker | 同所选宿主 | 同宿主文档 |
| worker_usage | cost_usd 优先；tokens = input + output + cache_write，不含 cache_read；拿不到填 null。DeepSeek 后端下 Claude Code 的 cost_usd 按 Claude 价格算，不可信：以 DeepSeek 控制台账单为准，task 记录 notes 标注 `billing:deepseek` | cost_usd 填 null，tokens 照常 |
| schedule_checkin | 同所选宿主 | 同宿主文档 |
| remote_workers | 路径一：仅 B 通道，且该通道是 Claude 后端；路径二：见 codex.md | 无云端时只用本地 A/W |
| local_machine | 同所选宿主（C 通道依赖云端会话，仅路径一的云端主会话可用） | 主会话直接在本机运行 |
| concurrency_limit | 同所选宿主；DeepSeek 的并发/速率限制待核实 | 先过 resources.sh，保守并发 |

## 3. 档位映射 T0–T4 →（模型, 思考深度）

### 路径一：Claude Code

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

### 路径二：Codex

在 Codex 模型提供方配置里使用 deepseek-v4-flash / deepseek-v4-pro，按 codex.md 的方式映射档位（建议 T0–T2 → flash，T3–T4 → pro，思考深度同上）。Codex 模板文件名与 reasoning 字段以 codex.md 为准。

## 4. 安装与调用

安装技能：`./install.sh --host claude|codex|both`（见仓库根目录）。调用方式同宿主（Claude Code 用 `/hq`；Codex 见 codex.md）。

### 路径一配置示例（bash）

```bash
export ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic"
export ANTHROPIC_AUTH_TOKEN="<YOUR_DEEPSEEK_API_KEY>"   # 占位符，替换为自己的 key，不要提交到仓库
export ANTHROPIC_DEFAULT_OPUS_MODEL="deepseek-v4-pro"   # 官方示例为 deepseek-flash[1m]；改 pro 见上文，待核实
export ANTHROPIC_DEFAULT_SONNET_MODEL="deepseek-flash"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="deepseek-flash"
export CLAUDE_CODE_EFFORT_LEVEL="max"                   # 官方建议；hq 按档位另设 effort，是否被它覆盖待核实
# 不要设置 CLAUDE_CODE_SUBAGENT_MODEL（原因见第 3 节）
```

变量名 `ANTHROPIC_BASE_URL`、`ANTHROPIC_AUTH_TOKEN` 为 Claude Code 通用写法，DeepSeek 页具体用哪个待核实。

### 路径二配置示例（`~/.codex/config.toml`，依官方“Integrate with Codex”摘要，字段细节待核实）

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
- cost_usd 在 DeepSeek 后端下可能不准（Claude Code 按 Claude 价格计算）：以 DeepSeek 控制台账单为准，notes 标注 `billing:deepseek`。
- B 通道不可用或不走 DeepSeek：用 Claude 模型和 Claude 套餐额度，混用时账单要分开记。
- flash 对 T3/T4 的质量风险：复盘看这两档的一次通过率。
- 待核实：Claude Code 与 Codex 的适用版本；opus 变量设为 deepseek-v4-pro 是否被官方认可；DeepSeek 并发/速率限制；`CLAUDE_CODE_EFFORT_LEVEL` 与 hq 按档位 effort 的关系；Codex 配置字段是否随版本变化；官方示例里 `deepseek-flash` 与 `deepseek-v4-flash` 两个名字是否等价。
