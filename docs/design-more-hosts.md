# 设计草案：支持更多代理工具（OpenCode、Cursor、Gemini CLI 等）与一键安装

状态：v0.4.0 已实现第 4.2、4.3 节（登记表、`--host auto`、最小目录集合、`--list/--update/--uninstall`）、4.1 的引导脚本和 `npx skills add` 说明，以及通用宿主文档；v0.4.1 实现了 4.4 的模板生成器（codex、opencode 两种格式）和第 5 节的 OpenCode 原生适配；v0.4.2 实现了第 6 节的 W 后端（opencode、gemini、cursor）；v0.4.3 实现了 Gemini 扩展清单和 Gemini CLI 原生宿主（扩展不带子代理，见 `adapters/gemini/README.md`）；剩下 Cursor 原生子代理，等子代理格式和模型选择核实后再做。外部工具的路径和参数来自 2026-11-25 的官方文档检索，**未实机运行**，标“待核实”的必须实机确认后才能写进宿主文档。

## 1. 现状与问题

- `install.sh` 用 `case` 硬编码 claude / codex / dsh 三个宿主；每加一个宿主要改安装脚本、测试、SKILL.md 的 `find` 路径、README 两份。
- 其他工具在 `runtimes.md` 里只有一行“识别不了：有 shell 用 W，否则降级”。
- `cli-worker.sh` 只认 `codex|claude`。
- 安装要先 clone 仓库，再选 `--host`，不算“一键”。

## 2. 关键事实：技能文件本身已经基本“通用”

| 工具 | 读取的技能目录（项目 / 个人） | 子代理 | 子代理能否按任务指定模型 | 非交互 CLI（W 通道候选） |
|---|---|---|---|---|
| Claude Code | `.claude/skills` / `~/.claude/skills`；插件市场 | Agent 工具 | 能（model 参数） | `claude -p`（已支持） |
| Codex | `.agents/skills` / `~/.agents/skills` | 自定义 agent（`.codex/agents/*.toml`） | 能（按 agent 模板） | `codex exec`（已支持） |
| dsh | `.dsh/skills`、`.agents/skills` / `~/.dsh/skills`、`~/.agents/skills` | `subagent` | 能（逐次传） | 待核实 |
| **OpenCode** | `.opencode/skills`，**也读 `.claude/skills`、`.agents/skills`**；个人 `~/.config/opencode/skills` 及对应 home 目录 | `.opencode/agents/*.md`（`mode: subagent`） | 能：frontmatter `model: provider/model#variant`，每档一个 agent 即可 | `opencode run`（`--model` 参数待核实） |
| **Cursor** | `.cursor/skills`，**也读 `.claude/skills`、`.codex/skills`**（项目和个人）；`.agents/skills` 有论坛讨论，待核实 | `.cursor/agents/*.md`（二手资料；格式、能否设模型待核实；2.4 时子代理不能用技能） | 待核实 | `agent -p --output-format json`（`--model` 待核实；团队可禁用 headless） |
| **Gemini CLI** | `.gemini/skills`、`.agents/skills` / `~/.gemini/skills`、`~/.agents/skills`；扩展可打包技能和子代理 | `.gemini/agents/*.md`，`invoke_agent` 调用 | 能，但在 `settings.json` 的 `agents.overrides.<name>.modelConfig` 里设，不在 frontmatter | `gemini -p -m <model> --output-format json`（输出含 `stats`，可解析用量） |
| 其他（Copilot、Windsurf、Amp、Kiro…） | 多数读 `.agents/skills` 或 `.claude/skills` | 各异 | 各异 | 各异 |

结论：

1. **技能分发**只需两个目录就能覆盖绝大多数工具：`~/.agents/skills`（Codex、dsh、OpenCode、Gemini CLI，可能还有 Cursor）和 `~/.claude/skills`（Claude Code、OpenCode、Cursor）。难点不在“装到哪”，而在每个宿主的**派发能力和档位映射**。
2. 装到多个被同一工具读取的目录会**重复发现**（例如 OpenCode 同时读 `.claude/skills` 和 `.agents/skills`）。安装器要按“覆盖所需工具的最小目录集合”安装，而不是每个工具各装一份。
3. 社区已有通用安装器 `npx skills add <owner/repo>`（vercel-labs/skills，支持 75+ 个代理，`-a opencode -a cursor` 选择目标）。我们的仓库结构 `skills/<name>/SKILL.md` 已符合它的约定，几乎零成本就能接入。

## 3. 总体方案：三层

```
L1 技能分发   把 skills/hq、skills/hq-retro 放到工具能发现的目录（安装器负责）
L2 宿主适配   hosts/<host>.md + 档位映射 + 可选子代理模板（让 T0–T4 真正生效）
L3 W 通道后端  cli-worker.sh 的 CLI 后端（任何有 shell 的宿主都能跨工具派活）
```

一个新工具按 L1 → L3 → L2 的顺序接入：L1 当天可用（降级模式），L3 让它能被别的宿主当 worker 用，L2 让它自己当总指挥时档位生效。

## 4. 一键安装

### 4.1 安装入口（按优先级）

| 入口 | 命令 | 覆盖 | 维护成本 |
|---|---|---|---|
| ① 引导脚本 | `curl -fsSL https://raw.githubusercontent.com/lostoy0/hq-orchestrator/<tag>/install.sh \| bash -s -- --host auto` | 全部宿主 + 子代理模板 | 中 |
| ② 通用技能安装器 | `npx skills add lostoy0/hq-orchestrator`（可加 `-a opencode -a cursor`） | 75+ 工具，只装技能 | 几乎为零 |
| ③ 原生插件/扩展 | Claude：`/plugin marketplace add`（已有）；Gemini：`gemini extensions install https://github.com/lostoy0/hq-orchestrator` | 各自工具，可带子代理 | 低 |

- ① 是主入口：脚本检测到不在仓库内运行时，先把指定 tag 下载到 `~/.hq-orchestrator/<版本>`（git clone 或 tarball），再执行本地安装逻辑。必须固定 tag（不用 main），并默认先打印将要写入的路径（等同 `--dry-run` 的摘要）再执行。
- ② 只需在 README 写一行并实测：确认它会把 `scripts/`、`references/` 整个目录一起复制（待核实），否则 `resources.sh`、`cli-worker.sh` 找不到。
- ③ Gemini 扩展只要在仓库根目录加 `gemini-extension.json`，并让扩展内的 `skills/`、`agents/` 指向现有内容。

### 4.2 `--host auto`：自动检测 + 最小目录集合

检测规则（命令存在或配置目录存在任一即算已安装）：

| 宿主 | 检测 |
|---|---|
| claude | `command -v claude` 或 `~/.claude/` |
| codex | `command -v codex` 或 `~/.codex/` |
| dsh | `$DSH_HOME` 或 `~/.dsh/` |
| opencode | `command -v opencode` 或 `~/.config/opencode/` |
| cursor | `command -v cursor-agent`/`agent` 或 `~/.cursor/` |
| gemini | `command -v gemini` 或 `~/.gemini/` |

然后按注册表里每个宿主“读取哪些目录”求一个**最小覆盖集合**：典型结果是只装 `~/.agents/skills` + `~/.claude/skills` 两处，打印“哪些工具会通过哪个目录读到”。用户可用 `--host opencode,cursor` 显式指定，`--layout per-host` 强制每个工具各装自己的专属目录。

### 4.3 宿主注册表（取代 `case` 硬编码）

新增 `adapters/hosts.tsv`（纯文本，bash 直接读，不引入 jq/yq 依赖）：

```
# id      detect_cmd     detect_dir             user_skill_dir             project_skill_dir  also_reads                   agent_fmt  user_agent_dir             project_agent_dir
claude    claude         ~/.claude              ~/.claude/skills           .claude/skills     -                            claude-md  ~/.claude/agents           .claude/agents
codex     codex          ~/.codex               ~/.agents/skills           .agents/skills     -                            codex-toml ~/.codex/agents            .codex/agents
dsh       -              ${DSH_HOME:-~/.dsh}    ${DSH_HOME:-~/.dsh}/skills .dsh/skills        agents                       -          -                          -
opencode  opencode       ~/.config/opencode     ~/.config/opencode/skills  .opencode/skills   claude,agents                opencode-md ~/.config/opencode/agents .opencode/agents
cursor    cursor-agent   ~/.cursor              ~/.cursor/skills           .cursor/skills     claude,codex                 cursor-md  ~/.cursor/agents           .cursor/agents
gemini    gemini         ~/.gemini              ~/.gemini/skills           .gemini/skills     agents                       gemini-md  ~/.gemini/agents           .gemini/agents
```

- `install.sh`、`tests/test_install.sh`、SKILL.md 的脚本查找路径都从这张表来；新增宿主 = 加一行 + 一份 `hosts/<id>.md`。
- 同时补齐运维子命令：`--list`（检测结果与将装位置）、`--update`（按已装位置覆盖为新版本）、`--uninstall`。每个安装位置写一个 `.hq-install.json`（版本、来源 tag、宿主），供 `--update`/`--uninstall` 和 `/hq-retro` 判断版本。
- 保持现有约定：先检查全部目标再写、退出码 0/2/3、默认不改任何用户配置。

### 4.4 子代理档位模板：一份源，生成多种格式

现在 `adapters/codex/agents/hq-t0…t4.toml` 是手写的。再加 OpenCode、Cursor、Gemini、Claude 后会变成 5×5 个手写文件，容易漂移。改为：

- `adapters/tiers.tsv`：T0–T4 的角色说明、思考深度、各宿主默认模型（占位符）。
- `adapters/render.sh <fmt>`：渲染成 `codex-toml`、`opencode-md`（`mode: subagent`、`model: provider/model#variant`）、`gemini-md`（模型写进 `settings.json` 片段，**只打印、不自动改配置**）、`cursor-md`、`claude-md`。
- 安装时 `--with-agents` 渲染到注册表里的 agent 目录；`--model-map T0=…,T3=…` 直接填模型，不填则保留占位符并提示。
- 现有 `--with-codex-agents` 保留为别名。

## 5. 宿主适配（L2）

每个新宿主一份 `hosts/<id>.md`，沿用现有 5 节结构（概述、能力表、档位映射、安装与调用、待核实项）。预判：

| 宿主 | spawn_worker | 档位能否生效 | 主要缺口 | 建议优先级 |
|---|---|---|---|---|
| OpenCode | 调用 `hq-t0…hq-t4` 子代理 | 能（每个 agent 文件带 model） | 用量读取、停止子代理、v1/v2 配置差异 | **高**：能力最接近 Codex，且已读 `.claude/skills` |
| Gemini CLI | `invoke_agent` 调 `hq-t*` | 能（靠 `agents.overrides`，需用户改 settings） | 子代理模型不在 frontmatter；技能激活要用户同意 | 中：有扩展机制，安装体验最好 |
| Cursor | 子代理能力待核实 → 首选 W（`agent -p`） | 走 W 时能（若 `--model` 可用） | 子代理格式和模型、团队可禁 headless | 中：用户多，但先以“降级 + W”上线 |
| 其他 | — | 否 | — | 只做 L1，走降级模式 |

SKILL.md 第 1 步的识别改为：先读 `runtimes.md` 的识别表（从注册表衍生），识别不了用 `hosts/generic.md`（降级 + W 的通用说明），而不是在 SKILL.md 里继续追加宿主分支。

脚本查找：SKILL.md 现在用一串 `find` 路径找 `resources.sh`。宿主变多后改为：安装器在 `~/.hq/skill-path` 写入实际安装路径，SKILL.md 先读它，读不到再按注册表路径 `find`。

## 6. W 通道后端（L3）

`cli-worker.sh` 拆成“公共框架 + 每个 CLI 一个后端文件”：

```
scripts/cli-worker.sh            参数解析、worktree、状态文件、沙箱/危险开关（不变）
scripts/backends/codex.sh        build_cmd / parse_usage
scripts/backends/claude.sh
scripts/backends/opencode.sh     opencode run --model <provider/model> …（参数待核实）
scripts/backends/cursor.sh       agent -p --output-format json [--model] …（--model 待核实）
scripts/backends/gemini.sh       gemini -p -m <model> --output-format json；用量取 stats
```

- 每个后端必须声明沙箱映射；映射不了 `read-only` 的直接拒绝该组合（退出码 2），不静默降级。
- `worker_clis` 授权区照旧：默认空，跨厂商需显式开启。
- `tests/fixtures/fake-cli/` 为每个新 CLI 加假实现，测试只校验参数拼装和用量解析。

## 7. 分阶段落地

| 版本 | 内容 | 验收 |
|---|---|---|
| v0.4.0 | 注册表 + `--host auto`/列表/更新/卸载 + 引导脚本 + README 写 `npx skills add`；新增 opencode/cursor/gemini 的 L1（降级模式） | `test_install.sh` 覆盖每个注册表宿主 × 两个范围、auto 最小集合、重复发现检查；在 3 个工具里实测能触发 `/hq` |
| v0.4.1 | 模板生成器；OpenCode 宿主文档 + `opencode-md` 模板 | OpenCode 实机跑通 T0 和 T3 各一个任务，PLAYBOOK 写入映射 |
| v0.4.2 | `cli-worker.sh` 后端化 + opencode/gemini/cursor 后端 | 假 CLI 测试通过；每个后端实机跑 1 次 `start/status/usage/stop` |
| v0.4.3 | Gemini 扩展清单 + 宿主文档；Cursor 宿主文档（子代理核实后） | `gemini extensions install` 实机安装成功 |

每项按 CHANGELOG 约定登记“待验证”和验收指标；`metrics.py` 的 3c（按宿主/通道）自动覆盖新宿主。

## 8. 风险

- **重复发现**：同一工具从两个目录读到同名技能。默认最小集合安装；测试里断言 auto 不会为同一工具装两份。
- **文档漂移**：这些工具更新快（OpenCode 有 v1/v2 两套配置，Cursor 的子代理资料多为二手）。宿主文档注明核对日期和来源，`/hq-retro` 遇到参数报错时提示更新宿主文档。
- **curl | bash 的信任问题**：固定 tag、先打印计划、提供 `--dry-run`，并在 README 给出“先下载再看再运行”的写法。
- **改用户配置**：Gemini 子代理模型需要改 `settings.json`。安装器只打印要加的片段，不自动写入，保持“只复制文件”的承诺。
