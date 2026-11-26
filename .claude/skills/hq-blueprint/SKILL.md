---
name: hq-blueprint
description: HQ 一键蓝图。仅在用户显式输入 /hq-blueprint 时使用：从一句想法或已有文档出发，按顺序把竞品调研、需求、设计、架构、计划几个阶段串起来跑完（已经做好且没过期的阶段跳过，过期或有问题的补全），设计和架构并行，阶段之间有检查关卡，只在需求阶段之后就改不回来的决定问一次，最后产出一份项目蓝图索引；可选接着执行第一个版本。用户只是说“帮我规划一下”时不要自动使用。
argument-hint: "[产品描述] [--until research|prd|design|arch|plan|build] [--from <阶段>] [--skip <阶段,…>] [--no-pause] [--ask] [各阶段参数如 --n --platform --stack]"
disable-model-invocation: true
license: "Apache-2.0 with Commons Clause v1.0 (https://github.com/lostoy0/hq-orchestrator/blob/main/LICENSE)"
---

# HQ 一键蓝图（/hq-blueprint）

一条命令把“想法”推进到“可以开工的计划”：`/hq-research → /hq-prd → /hq-design 与 /hq-arch（并行）→ /hq-plan`，可选再接 `/hq --backlog R1`。本技能只管**串联**：每个阶段怎么做，完全按那个阶段自己的技能执行。

## 先读

1. 找 hq 技能目录 `<hq>`：本文件同级的 `../hq/`（里面有 `SKILL.md`）；没有就读 `~/.hq/skill-path`；再没有就用 shell 查找：`find ~/.claude/skills ~/.claude/plugins ~/.agents/skills ~/.dsh/skills ~/.config/opencode/skills ~/.cursor/skills ~/.gemini/skills ~/.gemini/extensions/hq-orchestrator/skills .claude/skills .agents/skills .dsh/skills .opencode/skills .cursor/skills .gemini/skills -path '*hq/SKILL.md' 2>/dev/null | head -1`，取其目录。各阶段技能在 `<hq>` 的同级目录（`../hq-research/` 等）。
2. 读 `<hq>/SKILL.md`（主流程）和 `<hq>/references/stages/common.md`。各阶段的 `SKILL.md` 等轮到它时再读，不要一开始全部读进来。
3. 台账头部写 `stage: blueprint`，以及本次要跑的阶段列表。

## 参数

- 命令后面的文字：产品描述，传给第一个要跑的阶段。项目里什么文档都没有、也没写描述时，问用户一句产品是什么（唯一必须等的输入）。
- `--until <阶段>`：跑到哪个阶段为止，默认 `plan`。`build` 表示计划做完后接着执行第一个版本（`/hq --backlog R1`，合并和开 PR 按 PLAYBOOK 授权）。
- `--from <阶段>`：从这个阶段开始强制重跑（即使它已是最新），下游随之对齐。
- `--skip <阶段,…>`：跳过的阶段，例如纯后端服务 `--skip design`，已有充分市场认识 `--skip research`。被跳过的阶段在蓝图索引里写明原因。
- `--no-pause`：需求阶段之后有待决定事项也不停（见第 3 节）。
- `--ask`：传给每个阶段（各阶段在写作前先问自己的待决定事项）。
- 各阶段参数原样转给对应阶段：`--n`、`--deep`、`--market` 给 research；`--from`（需求输入）、`--scope` 给 prd；`--platform`、`--explore`、`--brand`、`--figma` 给 design；`--stack` 给 arch；`--release`、`--horizon` 给 plan。和本技能同名的参数（`--from`）写成 `--prd-from <路径>`。

## 1. 侦察：哪些阶段要跑

运行 `python3 <hq>/scripts/stage-status.py --docs <docs_root> --format json`（`docs_root` 按 `common.md` 第 2 节确定）。它对每个阶段给出状态：

| 状态 | 含义 | 本次怎么做 |
|---|---|---|
| `ok` | 产物齐全、检查没有错误、依据的上游版本是最新的 | 跳过（除非在 `--from` 之后） |
| `missing` | 没有产物 | 新建 |
| `partial` | 产物不全 | 补全模式 |
| `needs_work` | 检查有错误 | 补全模式 |
| `stale` | 依据的上游已更新 | 补全模式，先对齐上游的变化 |

再按 `--until`、`--skip`、`--from` 定出本次要跑的阶段。**上游阶段一旦重跑，它下游所有已存在的阶段都要跟着对齐**（上游版本变了，下游会变成 `stale`）。

开始前给用户发一条通知（不等确认，PLAYBOOK `autonomy: confirm-plan` 时才等）：每个阶段的状态、本次跑哪些、为什么跳过哪些、预计子任务数和大致花费；超过 `budget_usd` 时按 hq 停止条件 2 先问。

## 2. 顺序与并行

```
research → prd → design（g1 侦察、g2 页面与流程）→ design 其余步骤
                                              ↘ arch（与 design 并行）
                                     design + arch 都完成 → plan → build（可选）
```

- 每个阶段按它自己的 `SKILL.md` 执行（读到它时再读），用它的任务图、评审和完成标准；本技能不改阶段内的做法。
- **design 和 arch 并行**：design 的页面与流程（g2）完成后就开始 arch，arch 读 `design/screens.md` 了解前端页面；两边同时推进，缩短总用时。跳过 design 时，arch 在 prd 之后直接开始。
- 每个阶段在台账里是一个独立区块，有自己的 `run_id`（`<蓝图 run_id>-<阶段>`），各自写 run 记录，便于按阶段复盘；本技能另写一条 `stage: blueprint` 的 run 记录，加 `stages_run`（实际跑了哪些阶段）。
- 主会话只做串联和关卡判断，阶段内的写作和评审都派给子会话（hq 铁律 1）。上下文吃紧时，按 hq 主流程把每个阶段的结论压缩进台账再继续。

## 3. 关卡

**阶段关卡**（每个阶段结束、下一个阶段开始前）：
- 再跑一次 `stage-status.py`，这个阶段必须是 `ok`；评审没有未解决的 blocker。
- 不满足时，在该阶段的轮次上限内补一轮修改；仍不满足就**停在这里**，汇报卡在哪、为什么，不在有问题的基础上继续往下做。

**决策暂停**（需求阶段之后，只停这一次）：
- 需求文档里有未决的 `D-xx`（商业模式、目标市场这类）时，停下来一次性问用户，每条附推荐选项。
- 理由：单个阶段里按推荐先写没问题，但在蓝图里，这些决定会被设计、架构、计划三个阶段层层依赖，猜错的返工远超 hq 停止条件 3 的“约 1 小时”门槛。
- 等待期间可以先做不依赖这些决定的只读工作（design 和 arch 的侦察）。
- 带 `--no-pause` 时不停，按推荐继续，在蓝图索引里醒目列出这些未确认的决定。
- 其他阶段新产生的 `D-xx` 不再单独停，统一在最后汇报。

## 4. 蓝图索引

全部跑完（或停在某个关卡）后，写 `<docs_root>/blueprint.md`，作为整个项目的入口：

```markdown
---
hq_stage: blueprint
version: <每次运行加 1>
updated: YYYY-MM-DD
---
# <产品名> 项目蓝图

一句话定位：<来自需求文档>

## 阶段与产物
| 阶段 | 状态 | 产物 | 版本 | 本次 | 评审（轮次 / 未解决） |
|---|---|---|---|---|---|

## 待你决定（D-xx，汇总自各产物）
## 主要假设（A-xx，汇总自各产物，只列影响大的）
## 首个版本（来自计划）
## 下一步
```

内容只从各产物里汇总，不重新写；每条都写出处（文件和编号）。

## 5. 完成标准

1. 本次要跑的每个阶段都满足它自己的完成标准，`stage-status.py` 显示为 `ok`（停在关卡时写明哪个阶段、什么原因）。
2. 下游阶段依据的上游版本是最新的（没有 `stale`）。
3. 决策暂停按第 3 节执行；未确认的决定在蓝图索引里列出。
4. 蓝图索引写好，链接都能打开，汇总的每一条都有出处。
5. `--until build` 时，第一个版本按 `/hq --backlog` 的规则执行完，回写了计划清单。

## 6. 汇报

按 hq 主流程第 10 步，再加以下内容：
- 阶段表（同蓝图索引）和总用时、总花费，各阶段分别多少；
- 每个阶段一两句结论（产品定位、首版范围、设计方向、架构概要、版本计划）；
- 待你决定的事项（附推荐）和主要假设；
- 下一步：`/hq --backlog R1` 开始开发（`--until build` 时已执行，写执行结果）；开发完成准备上线时运行 `/hq-launch`。
