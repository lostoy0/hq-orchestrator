# hq-orchestrator：司令部模式

中文 | [English](README.en.md)

在普通会话里（Claude Code、Codex 等，本地或云端都可以）实现类似 Projects 的工作方式：**主会话负责统筹，子会话负责执行**。主会话记录每次运行的数据，`/hq-retro` 用这些数据复盘，让插件越用越准。

> **优化目标**：先过质量门槛（不漂移 + 验证到位 + 问题少），再求总用时最短，最后求成本最低。

**目录**

| 入门 | 使用 | 配置 | 参考 |
|---|---|---|---|
| [它解决什么](#它解决什么)<br>[快速开始](#快速开始)<br>[命令速查](#命令速查) | [基本用法](#基本用法)<br>[常驻模式](#常驻模式让一个会话一直当总指挥)<br>[阶段技能](#阶段技能从想法到上线)<br>[自主执行与停止条件](#自主执行与停止条件) | [授权配置](#授权配置)<br>[辅助执行者](#辅助执行者主模型主攻难点codex--kimi-承接中低难度)<br>[W 通道与跨厂商 worker](#w-通道与跨厂商-worker) | [安装](#安装)<br>[升级与卸载](#升级与卸载)<br>[复盘与数据](#复盘与数据)<br>[支持的宿主](#支持的宿主)<br>[设计要点](#设计要点)<br>[仓库结构](#仓库结构)<br>[自测](#自测)<br>[待核实项](#待核实项与本机验证清单)<br>[已知限制](#已知限制) |

---

## 它解决什么

大目标丢给单个会话，容易跑偏、只能串行、上下文被撑爆。`/hq` 让主会话只做统筹：

1. **判断值不值得拆**：预计不到约 30 分钟或高度耦合的工作，直接自己做。
2. **拆成任务图**：优先缩短关键路径，小而相关的任务打包。
3. **按难度配模型**：每个子任务按 5 维打分得到 T0–T4 档位，再换成宿主里具体的模型和思考深度。
4. **按资源控并发**：派发前检测 CPU、内存，本地跑不下就排队或放到云端。
5. **审核归并**：子会话的结果审核通过才合入；巡检时把已交付的合成一组、一次校验，全量测试攒到检查点再跑。
6. **记录与复盘**：每次运行的用量和结果写进 `.hq/runs/`，`/hq-retro` 据此校准选档。

**成熟度**：Claude Code 是主要宿主，实际用过；其他宿主的适配按官方文档完成，多数还没实机运行，见[支持的宿主](#支持的宿主)和[已知限制](#已知限制)。

## 快速开始

**Claude Code**（插件方式）：
```
/plugin marketplace add lostoy0/hq-orchestrator
/plugin install hq-orchestrator@hq-orchestrator-marketplace
```

**Codex、OpenCode、Gemini CLI、Cursor、dsh**（一行脚本，自动检测本机装了哪些工具）：
```bash
curl -fsSL https://raw.githubusercontent.com/lostoy0/hq-orchestrator/v0.10.6/install.sh | bash -s -- --host auto
```

装好后重开会话，给它一个目标：
```
/hq 给 api 服务加上导出 CSV 功能，并补齐测试和文档
```
它会把计划（任务表、各任务的档位和模型、运行位置、并发数、预计用时）作为通知发给你，**不等确认就开始派发**。进度随时可以问，也可以直接看 `.hq/LEDGER.md`。跑过几次之后，运行 `/hq-retro` 复盘。

其他安装方式（项目内副本、云端会话、Gemini 扩展等）见[安装](#安装)。

## 命令速查

| 命令 | 作用 |
|---|---|
| `/hq <目标>` | 统筹完成一个目标（一批） |
| `/hq --stay [目标]` | 常驻模式：本会话一批接一批地统筹，直到你说“退出常驻” |
| `/hq --backlog R1` | 按 `/hq-plan` 产出的计划清单执行一个版本 |
| `/hq --assist codex <目标>` | 本次把中低难度任务交给辅助执行者 |
| `/hq --assist codex --save` | 保存辅助执行者设置（所有项目），不开始运行；`--save-project` 只对本项目 |
| `/hq --assist-show` | 查看生效的辅助执行者设置并校验 |
| `/hq-retro` | 复盘运行数据，给出有证据的改进建议；`--export` 导出脱敏数据 |
| `/hq-research`、`/hq-prd`、`/hq-design`、`/hq-arch`、`/hq-plan` | 阶段技能：调研、需求、设计、架构、计划 |
| `/hq-blueprint` | 一键跑完上面的阶段，产出项目蓝图 |
| `/hq-launch` | 上线前按 46 项清单检查 |

用插件方式装在 Claude Code 里时，命令带前缀，如 `/hq-orchestrator:hq`。

---

## 基本用法

```
/hq 给 api 服务加上导出 CSV 功能，并补齐测试和文档；前端改动要在我本机跑 e2e
```

一次运行的过程：

1. **侦察**：读 `.hq/PLAYBOOK.md`（本项目的经验和授权），识别宿主、可用通道和本机资源。
2. **规划**：拆成任务图，写进台账 `.hq/LEDGER.md`，把计划作为通知发给你。
3. **派发**：按档位选模型，按资源控并发，需要本地资源的在本地跑，能并行的长任务放到云端。
4. **监控与调档**：子会话卡住就升一档新开会话，从它的分支接着做。
5. **审核归并**：审核通过才合入集成分支，每次巡检把已交付的一起合入、一起校验，全量测试只在检查点跑；合入默认分支、开 PR 默认要问你。
6. **汇报与记录**：汇报结果，把用量写进 `.hq/runs/`。

## 常驻模式：让一个会话一直当总指挥

默认 `/hq <目标>` 只管一批。想在同一个会话里一批接一批地推进（比如会话已经有很多上下文，不想换新会话），用常驻模式：
```
/hq --stay 先把导出 CSV 做完
```

- **不给目标**：只输入 `/hq --stay` 时，它先探索项目（台账、路线图、TODO、open issue、最近提交、测试状态等；项目大时派只读子任务去看），给出带编号和来源的推荐任务，然后等你选：回复“做 1、3”只做选中的，回复“按推荐”全部做，或者直接说你自己的目标。进入时一定等你选，不会自动开始。没找到明确的待办时，它会说明查过哪些地方，请你给目标。
- **继续下一批**：直接说下一个目标，例如“下一批：给导出加权限校验”。每批做完会汇报，末尾写“常驻中，等待下一个目标”；中间提问不会退出。
- **自动推荐**：每批汇报后推荐下一批（最多 5 条，每条附来源、预计档位和用时），来源是台账待办、之前对话里没做完的事、路线图、TODO、open issue 和失败的测试。一条可执行的都没有、总目标也已达成时，它会明确说“项目当前所有任务都已执行完毕，没有更多可执行任务了”，并列出检查过哪些来源。它不会为凑数编任务；要密钥、部署或需要你操作的事单独列出。想让它不等回复一直做下去，就说“按推荐自动继续”（仍受预算和停止条件约束）。
- **退出**：说“退出常驻”或 `/hq --stop`。

**接管一个已经开着的会话**：会话启动后才装的技能，通常要重开会话才会出现在 `/hq` 里。不想重开时，在那个会话里输入下面这句（路径换成你的技能目录，可用 `find ~/.claude ~/.agents -path '*hq/SKILL.md'` 查找）：
```
读取 ~/.claude/skills/hq/SKILL.md 全文，按其中“常驻模式”接管本会话：先把我们之前对话里已做完的事和已定的决策写进台账“接管背景”，然后等我给目标。
```
没有文件访问权限的会话，把 `PROMPT.md` 整段粘进去，再说“常驻”。

注意：
- 主会话会把技能路径记在 `.hq/LEDGER.md` 头部（`skill_path`），上下文被压缩后自己重读技能和台账。万一发现它开始亲自干活、不再派子会话，说一句“重新读取 SKILL.md，继续常驻”即可。
- 子会话看不到聊天记录，所以接管时之前的进度要写进台账“接管背景”。以后即使必须换新会话，也只要让新会话读 SKILL.md 和台账就能接上。
- 每批仍会先判断值不值得编排，小目标会直接自己做；要强制派发就在目标里写“这批也全部派出去”。

## 阶段技能：从想法到上线

`/hq` 管“怎么把活干完”，阶段技能管“该做出什么”，跑在同一套引擎上（台账、选档、派发、审核、记录都一样）。整体设计和路线见 `docs/design-stages.md`。

```
/hq-research 给独立开发者用的记账 App      # 联网调研竞品（默认 10 家、3 家深挖），每条结论附来源
/hq-research --n 6 --deep 2 --market global
/hq-prd                                   # 结合想法、截图、调研报告写出或补全需求文档
/hq-prd --scope 账号 --ask                 # 只补“账号”模块；关键决策先问
/hq-design --platform ios --explore 3     # 设计规范 + 能从头点到尾的高保真原型；先出 3 个风格方向
/hq-arch --stack nextjs,postgres          # 架构设计和详细设计，带全景架构图和决策记录
/hq-plan                                  # 读需求、设计、技术文档和现有代码，产出版本计划和任务清单
/hq-plan --release MVP 一个人做，两周内上线
/hq --backlog R1                          # 按清单执行第一个版本（也可以直接说“执行 R1”）
/hq-blueprint 给独立开发者用的记账 App     # 一键：调研 → 需求 → 设计和架构（并行）→ 计划，跳过已完成的阶段
/hq-blueprint --until build --skip design  # 一直做到执行第一个版本；纯后端产品跳过设计
/hq-launch                                # 上线前按 46 项清单检查，给出能不能上线的结论
```

### 各阶段产出

| 技能 | 产物 | 要点 |
|---|---|---|
| `/hq-research` | `docs/research/competitors.md` | 竞品分直接、间接、替代方案三类，深挖的写定位、功能、定价、用户规模、用户评价、优势短板；最后是对比矩阵、定价对比、机会点和“对需求的建议”。每条事实标来源编号，文末来源表写链接和访问日期，推断单独标出。不能联网时直接说明，不凭模型记忆冒充调研；你明确接受时可以加 `--offline`，报告会标明未核实。评审时研究员会抽查 5 条结论和来源是否一致 |
| `/hq-prd` | `docs/product/prd.md` | 目标用户、首版范围和“不做什么”、每个功能的用户故事、验收标准和全部界面状态、非功能需求、商业化、成功指标和埋点、上线必需项核对表（注册登录、找回密码、注销账号、隐私政策等 24 项，每项写包含、不做或不适用）、需求索引（`/hq-plan` 直接读）。没有调研报告时先做一次 5 家的竞品速览（`--no-research` 跳过）。已有需求文档时按上线标准补全，不删你写的内容；不是本格式的，原文件不动，另写一份。评审：设计、架构、测试，涉及账号、支付、个人信息时加安全 |
| `/hq-design` | `docs/design/` | 设计规范（设计变量、组件、交互、文案、可访问性）、页面与流程说明，以及一个能离线打开的高保真可点击原型。原型基于内置的起步套件：模拟登录和演示账号（新用户、老用户、付费、管理员等）、像真的模拟数据、每页的空、加载、错误、无权限、首次使用状态，主要流程（含注册登录）能从头点到尾，左下角工具条可切换页面、状态、账号。`prototype-check.py` 静态检查，`prototype-walk.mjs` 用 Playwright 逐页逐状态截图并把每条流程自动走一遍；再由设计角色看截图做视觉走查。默认风格简洁易懂又现代好看，并列出了要避免的“AI 风格”。评审：产品、开发、测试 |
| `/hq-arch` | `docs/tech/architecture.md`、`detailed-design.md`、`adr/` | 约束和质量属性、系统上下文、容器、组件、数据模型、关键流程时序、部署六类图（Mermaid，按 `skills/hq-arch/diagram-style.md` 的画法：一张图一层、节点不超过 15 个、子图画边界、连线写标签、统一配色）、模块职责和需求映射、非功能设计、技术选型和决策记录、风险与待验证（`/hq-plan` 会排成先行调研）。默认选成熟、托管、一个人维护得了的方案。评审：开发、安全、测试，有部署或成本约束时加运维 |
| `/hq-plan` | `docs/plan/roadmap.md`、`docs/plan/backlog.json` | roadmap 给人看：版本、范围、发布条件、依赖图、需求覆盖表；backlog 给 `/hq` 读：每个任务的依赖、负责的文件、验收标准、验证级别和按 5 维打分得到的预估档位。项目已有文档目录时沿用。等别人决定的任务（如待客户确认的范围变更）标 `hold`，`/hq` 不会派发；要真机、商店账号、支付测试账号、客户资料或人工核对的任务标 `needs_human`，AI 只准备脚本和检查清单，那一步交给你；要等外部就绪的写成里程碑（`milestones`、`ready_after`），关键路径会算上等待。评审：架构、开发、QA（没有需求文档时加产品） |
| `/hq-blueprint` | `docs/blueprint.md` | 一条命令把上面几个阶段串起来。先用 `stage-status.py` 看每个阶段的产物齐不齐、检查有没有错误、依据的上游是否已更新，只跑需要跑的；上游重跑后下游自动对齐。设计和架构并行。每个阶段结束都要过检查关卡，不过关就停在那里。需求阶段之后如果有商业模式、目标市场这类没定的大决定，停下来问你一次（`--no-pause` 不停）。最后写项目蓝图，汇总各阶段的产物、待你决定的事项和下一步 |
| `/hq-launch` | `docs/launch/checklist.md` | 产品完整性、质量、安全、隐私与合规、运维、运营与增长、商务、发布八个方面共 46 项。能用命令验证的实际去跑（全量测试、构建、依赖漏洞审计、密钥扫描），每项“通过”都要有证据，再由独立子会话抽查 5 条。结论按规则给出“可以上线 / 有条件上线 / 暂不上线”，列出阻塞问题和需要你确认的事项（备案、商店后台、真实支付这类只有你能看的）。缺少的材料会起草：运维手册、发布说明、上线运营计划、商店文案，以及隐私政策、用户协议、退款政策草稿（标明需法律专业人士审核，不构成法律意见）。它不部署、不发布 |

### 所有阶段共用的规则

- **评审**：多个角色并行评审，意见分阻塞、重要、次要三级；默认最多 2 轮，第 2 轮只核对阻塞和重要问题，到上限还没解决的交给你确认，不会无限来回。角色卡在 `skills/hq/references/roles/`。
- **决策**：按“合规与安全底线 > 用户价值与体验 > 商业可行 > 技术简单 > 成本”自己定。定价和商业模式、品牌命名、目标市场、法务风险这类改不回来的决定由你拍板，但不会卡住写作：先按推荐选项写，记成待决定事项，阶段结束时一次性问你（加 `--ask` 则写之前先问）；没决定前文档不能标为已批准。其他假设也一并列给你。
- **检查**：`skills/hq/scripts/backlog-check.py` 机械检查计划清单（编号唯一、依赖无环、档位和分数一致、P0 需求都有任务覆盖、没有任务依赖暂缓任务，并按外部里程碑算关键路径）；`skills/hq/scripts/doc-check.py prd|research|arch|launch` 检查需求文档、调研报告和架构文档（架构：每章的图齐全、节点数、统一配色、模块字段、需求都落到模块、ADR 格式；其余：字段齐全、界面状态写全、需求索引和正文一致、上线必需项每行有结论、引用的来源都在来源表里、每家竞品的来源数够）。
- **闭环**：`/hq` 执行时按当时的代码重新打分，记下计划预估的档位；`metrics.py` 报告“3e 计划预估档位 vs 实际”，`/hq-retro` 据此校准计划阶段的打分。
- **已有文档的项目**：项目里已经有需求、原型、技术设计、计划（别的工具生成的，或团队自己的格式）时，不会另起一套。`stage-status.py --discover` 先在全仓库找出这些文档，写成对应表 `hq-artifacts.json`；各阶段对外来格式的文档做**接管评审**：按完成标准判断内容，不看格式，编号照用。已冻结的文档只写修改提案交给你决定，没冻结的在原文件里按原结构补缺口。外来格式的计划由 `/hq-plan` 导入成 `backlog.json`，保留原编号，`/hq --backlog` 可以直接执行；原计划改了会提示重新导入。
- **不会被自动调用**：阶段技能很重，在 Claude Code 里设了 `disable-model-invocation`，只有输入命令才执行；其他宿主靠技能说明里的“仅在用户显式输入时使用”兜底。

## 自主执行与停止条件

- 技术方案、模型、拆分、重试都由主会话自己决定，每个决策记进台账“决策”区。
- 只有三种情况会停下来找你，问题攒齐一次问，每个附推荐选项，同时继续推进不受影响的工作：
  1. 需要密码、密钥、账号、付款，或需要你在界面上、在自己电脑上操作；
  2. 不可撤回或影响别人的操作且没有事先授权：删除数据或分支、部署、强制推送、对外发布、超出预算；
  3. 需求有歧义，调研后仍判断不了，且猜错的返工代价超过约 1 小时。
- 推送 `hq/*` 分支、合并到 `hq/integration` 默认自动；合入默认分支、开 PR 默认要问。

---

## 授权配置

写在项目的 `.hq/PLAYBOOK.md`“授权”区（第一次运行 `/hq` 时按模板 `skills/hq/references/playbook-template.md` 自动建好），一次设定、之后不再逐次询问：
```yaml
merge_default: ask        # ask | auto-if-gates-pass：质量门槛都通过时是否自动合入默认分支
open_pr: ask              # ask | auto
budget_usd: 20            # 单次运行的花费上限，超出前停下来问
remote_concurrency: 4     # 远程子会话并发上限（默认 4）；只调并发，不影响档位
max_subtasks: 12          # 单批最多派多少个子任务（默认 12）
autonomy: auto            # auto | confirm-plan：confirm-plan 时计划要等你确认再派发
worker_clis: []           # 跨厂商 worker，可选 codex/claude/opencode/gemini/cursor；默认空即关闭
runs_persist: off         # off | branch | commit：运行记录是否保存进仓库；云端没写时问一次
assist: …                 # 辅助执行者，见下一节；建议用命令配置
cost_weight: …            # 各计费方的额度成本，影响拿不准难度时往上选多少
```

## 辅助执行者：主模型主攻难点，Codex / Kimi 承接中低难度

默认关闭。大目标拆成很多子任务时，可以让主宿主只做难的、重要的任务，把需求明确的中低难度任务交给更便宜的模型，再由主宿主审核，以节省主宿主额度、增加并行度。**主宿主就是运行 hq 的那个宿主和模型**（Claude Code、Codex、Gemini CLI 等都可以），不一定是 Claude。

### 怎么工作

- **怎么分**（`skills/hq/calibration.md` 规则 10）：只有档位 ≤ `max_tier`（默认 T2）、风险低、需求明确、一条命令就能验证对错、且不是共享接口这类前置任务的，才交给辅助；T3/T4、架构、安全、数据、并发、迁移、根因不明的问题和所有审核都留给主宿主。
- **怎么审**：辅助的产出一律由主宿主审核，不按“审核降一档”的规则降档；改动超过约 150 行另派独立审核。
- **失败怎么办**：辅助失败一次，就由主宿主高一档从它的分支接手。辅助**不可用**（CLI 起不来、未登录、限流、缺密钥）立即停用；**连续失败 2 次**或累计失败达到 `max_failures`（默认 2）也停用。所有辅助都停用后，本次剩余任务**全部由主宿主自己做**，不会停下来问你，只在汇报里说明一次。
- **效果看数据**：task 记录多了 `assist` 字段，`metrics.py` 报告的“3d 辅助执行者 vs 主宿主”按档位对比一次通过率和回收率，`/hq-retro` 据此建议调低 `max_tier` 或停用某个辅助。
- **注意**：辅助走 W 通道，在本机（或云端容器）里运行，占本地 CPU 和内存；云端会话里要装好 CLI、放行接口主机、配好密钥，否则自动全部留给主宿主。外部模型失败重来会吃掉省下的额度，所以拿不准难度的任务不会交出去。

### 能配什么

| 项 | 说明 |
|---|---|
| 平台（profile） | `codex`（装了 codex CLI 就能用，模型自动读取）；`kimi` 等第三方接口经 `claude` CLI 接入，要 `env_file`（见 `skills/hq/references/hosts/kimi.md`，**只按公开资料整理，未实机运行**）；也可以用 `opencode`、`gemini`、`cursor` CLI。多个按顺序优先，前一个停用后用下一个 |
| 档位 | 只有 **T0–T2** 能交给辅助（`max_tier` 最高 T2）；T3、T4 和所有审核**始终由主宿主做**，用主宿主自己的映射（Claude Code 为 haiku/sonnet/opus，见 `skills/hq/references/hosts/claude-code.md` 第 3 节） |
| 每档模型、思考深度 | 每个 profile 的 `models`、`effort` 按 T0、T1、T2 分别填；codex 可以不填，按本机模型目录自动推荐；思考深度没填时 codex 按档位默认（T0/T1 low、T2 medium），其他 CLI 不传 |
| 和宿主的关系 | 配置不分宿主：在 Claude Code 里运行就用这份名单；在 Codex 里运行时 `codex` 和主宿主相同，自动跳过，用名单里的下一个（如 kimi） |
| 生效顺序 | 用户级 `~/.hq/config.yaml`（所有项目）< 项目 `.hq/PLAYBOOK.md` 的 `assist`（只这个项目）< 本次 `/hq --assist …` 参数，**逐项**覆盖：项目里只改 T2 的模型，其余照用用户级 |

### 只用一次

```
/hq --assist codex,kimi <目标>            # 本次运行，按顺序优先
/hq --assist kimi --assist-max T1 <目标>  # 只把 T0–T1 交出去
/hq --assist off <目标>                   # 本次关闭
```

### 配一次，一直生效

**场景 1：给所有项目统一配置（全局）**。在任意一个装了 hq 的项目里打开会话，输入：
```
/hq --assist codex --save
```
只保存、不开始运行：写进 `~/.hq/config.yaml`，codex 各档模型按本机 `codex debug models` 推荐填好，然后列出每档的模型和思考深度。想自己指定某几档：
```
/hq --assist codex --assist-models T0=gpt-6-luna,T1=gpt-6.2-sol,T2=gpt-6.2-astra --assist-effort T2=high --save
```
加 Kimi 作为第二个辅助（先按 `hosts/kimi.md` 第 4 节建好权限 600 的 `~/.hq/env/kimi.env`）：
```
/hq --assist kimi --assist-cli claude --assist-env-file ~/.hq/env/kimi.env --assist-models T0=<模型>,T1=<模型>,T2=<模型> --save
/hq --assist codex,kimi --save
```
也可以直接用中文说，例如“以后辅助都用 codex，T2 用 gpt-6.2-astra、思考 high，全局保存”。

**场景 2：只给某个项目配置**。在那个项目里打开会话，把 `--save` 换成 `--save-project`，写进该项目的 `.hq/PLAYBOOK.md`，只覆盖你写的那几项：
```
/hq --assist codex --assist-max T1 --save-project                    # 本项目只把 T0–T1 交出去
/hq --assist codex --assist-models T2=gpt-6.2-astra --save-project   # 本项目 T2 换个模型，其余沿用全局
/hq --assist off --save-project                                      # 本项目关闭辅助
```

**查看和校验**：`/hq --assist-show` 列出当前项目实际生效的名单、每档模型和思考深度、每项来自哪一层，并校验模型是否还在 codex 的模型目录里、思考深度是否支持、`env_file` 权限。

### 不进会话，用终端配置

命令和会话里一一对应（`set --scope user` = `--save`，`set --scope project --project <项目路径>` = `--save-project`）。脚本在 hq 技能目录的 `scripts/assist-config.py`，先找到它：
```bash
S=$(find ~/.claude/skills ~/.claude/plugins ~/.agents/skills "$PWD/.claude/skills" -path '*hq/scripts/assist-config.py' 2>/dev/null | head -1); echo "$S"
```

| 命令 | 作用 |
|---|---|
| `python3 "$S" models` | 本机 codex 可用的模型、支持的思考深度、下线时间 |
| `python3 "$S" suggest` | 推荐的 T0–T4 映射 |
| `python3 "$S" set --scope user --use codex --auto-models` | 全局启用 codex，模型按推荐填 |
| `python3 "$S" set --scope user --profile codex --models T2=gpt-6.2-astra --effort T2=high` | 全局改某一档 |
| `python3 "$S" set --scope project --project ~/code/my-app --max-tier T1` | 只改指定项目 |
| `python3 "$S" show --project ~/code/my-app` | 该项目生效的设置和来源 |
| `python3 "$S" check --project ~/code/my-app` | 校验模型、思考深度和 `env_file` |

**注意**
- 读取全局配置要求项目里的 hq 是 v0.10.5 或更新。按项目装的（`.claude/skills/hq`）旧副本不认 `~/.hq/config.yaml`，先在项目里升级：`./install.sh --update --scope project --project-dir <项目路径>`。
- codex 的推荐是按模型说明里的关键词推断的（模型目录里没有价格字段），保存后看一眼 `show` 的结果，不合适就用 `--assist-models` 改那一档。`--auto-models` 不会覆盖你填过的档位。
- 配置里只写 `env_file` 的路径，密钥只放在那个文件里；脚本不会读出或打印它的内容。
- Kimi 推荐经 `claude` CLI 接它的 Anthropic 兼容接口；`cli-worker.sh --env-file` 只把接口地址和密钥注入这个 worker 进程，值不写进日志。

## W 通道与跨厂商 worker

默认关闭。`skills/hq/scripts/cli-worker.sh` 在独立 git worktree（`.hq/worktrees/<id>`，分支 `hq/<id>`）里后台运行一个 CLI worker，任何有 shell 的宿主都能用：
```bash
cli-worker.sh start --id t2 --cli codex|claude|opencode|gemini|cursor --model <m> [--effort <e>] --brief <说明文件> [--sandbox read-only|workspace-write]
cli-worker.sh status|stop|usage --id t2      # 输出 JSON
cli-worker.sh list
```
- **开启**：用和宿主不同厂商的 CLI 做 worker（跨厂商），需要在 `.hq/PLAYBOOK.md` 授权区写 `worker_clis`（如 `[codex, claude]`）。宿主自己的 CLI（如 Gemini CLI 宿主用 `--cli gemini`）不需要授权，这也是 Cursor、Gemini CLI 宿主让档位生效的方式。
- **沙箱**：默认 `workspace-write`。`danger-full-access` 会关闭全部防护，**必须同时传 `--allow-dangerous`**，否则拒绝并以退出码 2 退出。
- **各 CLI**：命令和沙箱映射见 `skills/hq/references/runtimes.md` 的 W 节。opencode、gemini、cursor 三个后端只按文档和源码写成、用假 CLI 测过，**未实机运行**；opencode 和 cursor 没有“只限工作区”的沙箱，`workspace-write` 也会放开 shell。
- **用量**：`usage` 按统一口径算 tokens（input + output + cache_write，不含 cache_read）。

---

## 安装

### 选哪种方式

| 你的情况 | 推荐方式 |
|---|---|
| 只用 Claude Code，本地 | [Claude Code 插件](#claude-code-插件)，或[一行脚本](#一行脚本推荐所有宿主通用) `--host claude` |
| 用 Codex、OpenCode、Cursor、dsh，或几个工具一起用 | [一行脚本](#一行脚本推荐所有宿主通用) `--host auto` |
| 只用 Gemini CLI | [Gemini 扩展](#gemini-扩展) |
| 要在 Claude Code 云端会话里用，或要锁定项目里的版本 | [装进项目仓库](#云端会话与项目内副本) |
| 不想运行脚本 | [手动复制](#手动复制) 或 [`npx skills add`](#社区通用安装器) |

### 一行脚本（推荐，所有宿主通用）

```bash
curl -fsSL https://raw.githubusercontent.com/lostoy0/hq-orchestrator/v0.10.6/install.sh | bash -s -- --host auto
```
不在仓库里运行时，脚本先用 git 把 `v0.10.6` 标签下载到 `~/.hq-orchestrator/v0.10.6`，再执行安装。已 clone 本仓库的直接运行 `./install.sh`。完整说明用 `./install.sh --help` 查看。

**常用命令**

```bash
./install.sh --host auto                                   # 自动检测本机工具，装到个人目录
./install.sh --host claude --scope project                 # 只装进当前项目
./install.sh --host codex --with-agents --model-map auto   # 装 Codex，并按本机模型生成档位模板
./install.sh --list                                        # 先看会装到哪里，不写入
./install.sh --host auto --dry-run                         # 打印将要做的事，不写入
./install.sh --update                                      # 升级已装的副本
./install.sh --uninstall                                   # 删除已装的副本
```

**参数**

| 参数 | 作用 | 例子 |
|---|---|---|
| `--host <宿主>` | 装给哪些工具，逗号分隔。`auto` 自动检测；`all` 全部；可选 `claude`、`codex`、`dsh`、`opencode`、`cursor`、`gemini`；`both` 是旧写法，等同 `claude,codex` | `--host auto`<br>`--host claude,codex` |
| `--scope user\|project` | `user`（默认）装到个人目录，所有项目都能用；`project` 只装进一个项目 | `--scope project` |
| `--project-dir <路径>` | 配合 `--scope project` 指定项目，默认当前目录 | `--scope project --project-dir ~/code/my-app` |
| `--layout minimal\|per-host` | `minimal`（默认）只装到能覆盖所选工具的最少目录；`per-host` 每个工具装到自己的专属目录 | `--host claude,codex --layout per-host` |
| `--with-agents` | 同时安装子代理档位模板 `hq-t0…hq-t4`（codex、opencode、gemini 有模板） | `--host codex --with-agents` |
| `--model-map <映射>` | 生成模板时填入模型，只能配合一个宿主；codex、gemini 写模型名，opencode 写 `provider/model[#思考深度]`；codex 可写 `auto` | `--model-map auto`<br>`--model-map 'T0=<模型>,T3=<模型>'` |
| `--with-codex-agents` | 旧写法：只装 Codex 模板，不管 `--host` 是什么 | `--host claude --with-codex-agents` |
| `--dry-run` | 只打印将要做的事，不写入 | `--host auto --dry-run` |
| `--force` | 目标已存在时覆盖（默认不覆盖，退出码 3） | `--host claude --force` |
| `--list` | 显示检测结果、已装副本和安装计划，不写入 | `--list --scope project` |
| `--update` | 把本脚本装过的副本更新到当前版本 | `--update --scope project --project-dir ~/code/my-app` |
| `--uninstall` | 删除本脚本装过的副本（只删有安装记录的） | `--uninstall` |

**环境变量**

| 变量 | 作用 | 例子 |
|---|---|---|
| `HQ_REF` | 一行安装时下载哪个标签或分支，默认 `v0.10.6` | `HQ_REF=main` |
| `HQ_CACHE_DIR` | 下载缓存目录，默认 `~/.hq-orchestrator` | `HQ_CACHE_DIR=/tmp/hq` |
| `HQ_REPO_URL` | 从哪个 git 仓库下载，默认本仓库 | `HQ_REPO_URL=https://example.com/fork.git` |
| `DSH_HOME` | dsh 的主目录，默认 `~/.dsh` | `DSH_HOME=~/tools/dsh` |
| `CODEX_AGENTS_DIR`、`OPENCODE_AGENTS_DIR`、`GEMINI_AGENTS_DIR` | 改放子代理模板的目录 | `CODEX_AGENTS_DIR=~/tmp/agents` |

**会装到哪里**：`--host auto` 按命令（`claude`、`codex`、`opencode`、`cursor-agent`、`gemini`）或配置目录（`~/.claude`、`~/.codex`、`~/.dsh`、`~/.config/opencode`、`~/.cursor`、`~/.gemini`）检测本机装了哪些工具。很多工具会读同一个目录，默认只装到能覆盖所选工具的最少目录，同一工具不会读到两份；全部工具时只装两处：

| 目录（个人 / 项目范围） | 读取它的工具 |
|---|---|
| `~/.agents/skills` / `<项目>/.agents/skills` | codex、dsh、opencode、gemini |
| `~/.claude/skills` / `<项目>/.claude/skills` | claude、opencode、cursor |
| 各工具专属目录（只装一个工具时使用） | `${DSH_HOME:-~/.dsh}/skills`、`~/.config/opencode/skills`、`~/.cursor/skills`、`~/.gemini/skills`（项目范围为 `.dsh/`、`.opencode/`、`.cursor/`、`.gemini/` 下的 `skills/`） |

OpenCode 同时读前两个目录，Claude Code 和 Codex 都装时它会看到两份同名技能，按其规则只加载一份。

**子代理档位模板**（`--with-agents`）：让 T0–T4 在宿主里真正用到不同模型。Codex 装到 `~/.codex/agents/*.toml`，OpenCode 装到 `~/.config/opencode/agents/*.md`，Gemini CLI 装到 `~/.gemini/agents/*.md`（项目范围为 `<项目>/.codex/agents/`、`<项目>/.opencode/agents/`、`<项目>/.gemini/agents/`）。加 `--model-map` 会现场生成带真实模型的模板；不加时 Codex 模板是占位符（必须替换），OpenCode、Gemini 模板不设 model（继承父会话模型，档位不生效）。
```bash
./install.sh --host codex --with-agents --model-map auto
./install.sh --host opencode --with-agents --model-map 'T0=<p/小模型>,T1=<p/中档>,T2=<p/中档>,T3=<p/最强>,T4=<p/最强>'
```

**安装记录与退出码**：只复制文件，不改任何配置；会先检查所有目标，不会装一半。每个副本里写 `.hq-install.json`（版本、来源、宿主），个人范围另写 `~/.hq/skill-path` 供技能找到自己的脚本。退出码：0 成功；2 参数错误；3 目标已存在（加 `--force` 覆盖，或用 `--update`）；4 没有可操作的对象（未检测到工具、没有可更新或卸载的副本）；5 下载失败。

**装好后**：Codex 的调用方式见 `hosts/codex.md`；dsh 的首次运行步骤见 `hosts/dsh.md`；OpenCode 见 `hosts/opencode.md`；Gemini CLI 见 `hosts/gemini.md`；Cursor 见 `hosts/generic.md`。

### Claude Code 插件

```
/plugin marketplace add lostoy0/hq-orchestrator      # 或本地路径
/plugin install hq-orchestrator@hq-orchestrator-marketplace
```
装好后用 `/hq-orchestrator:hq <目标>`、`/hq-orchestrator:hq-retro` 调用。

### Gemini 扩展

只用 Gemini CLI 时最简单，带 `/hq`、`/hq-retro` 和各阶段命令：
```bash
gemini extensions install https://github.com/lostoy0/hq-orchestrator --ref v0.10.6
```
扩展只含技能和命令，不含子代理模板（同一个仓库也是 Claude Code 插件，根目录放 `agents/` 会被 Claude Code 当成自己的子代理）。要让档位生效，再运行 `./install.sh --host gemini --with-agents --model-map 'T0=…,…,T4=…'` 安装模板；与扩展同时装了技能时，Gemini CLI 优先用用户目录的副本，安装脚本会提示。

### 社区通用安装器

覆盖 70 多种代理工具，只装技能：
```bash
npx skills add lostoy0/hq-orchestrator                    # 交互选择工具
npx skills add lostoy0/hq-orchestrator -a opencode -a cursor
```
是否完整复制 `scripts/`、`references/` 待核实；缺脚本时资源检测和 W 通道不可用，此时请改用一行脚本。

### 手动复制

```bash
mkdir -p ~/.claude/skills && cp -r skills/hq skills/hq-retro skills/hq-plan skills/hq-prd skills/hq-research skills/hq-arch skills/hq-design skills/hq-blueprint skills/hq-launch ~/.claude/skills/
```
装好后在任意项目里输入 `/hq <目标>` 和 `/hq-retro` 即可使用。手动复制的副本没有安装记录，`--update` 不会处理它。

### 云端会话与项目内副本

云端会话每次都在新容器里从仓库 clone 代码，**读不到你本机的 `~/.claude`**，本机装的东西（包括本机 `/plugin install` 装的插件）都不会带到云端。实测云端会话能用的 skill 和插件来自两处：目标项目仓库里提交的 `.claude/skills/`，以及 claude.ai 账号或组织里启用的插件。

**推荐做法（云端已实测可用）：把 skill 复制进项目仓库并提交。**
```bash
./install.sh --host claude --scope project --project-dir <项目路径>
```
提交 `.claude/skills/` 后，基于这个仓库新开的云端会话都能用 `/hq`、`/hq-retro`，辅助脚本（如 `scripts/resources.sh`）也能正常运行。好处是不依赖网络和 marketplace，还能锁定版本；坏处是每个项目一份副本，要逐个升级。

**另一种做法：账号或组织级插件。** 在 claude.ai 的插件目录里给账号或组织启用它（前提是插件已在组织目录中，可能需要管理员上架）。

> ⚠️ **不要用项目 `.claude/settings.json` 声明插件来支持云端。** 用 `extraKnownMarketplaces` + `enabledPlugins` 声明 `hq-orchestrator@hq-orchestrator-marketplace` 的写法，2026-11 实测在云端**不会安装插件，也不报错**，skill 列表里没有 `hq-orchestrator:hq`。如果你照别处的教程这样配了却用不了，原因就在这里，改用上面的做法。

也可以用环境的 setup script 或 SessionStart hook 在每次开会话时运行 `install.sh`，但未实测，每次都要重装，一般不如上面的做法省事。

`.hq/`（台账、运行记录、复盘报告）默认不提交，云端容器回收后就没了。要在云端跨会话复盘，在 `.hq/PLAYBOOK.md` 里设 `runs_persist: branch`，见[复盘与数据](#复盘与数据)。

### 避免重复安装

| 情况 | 效果 | 建议 |
|---|---|---|
| 本机有个人副本（`~/.claude/skills/hq`），项目里又提交了项目内副本 | 本地在这个项目里会读到两个同名的 `/hq`，版本可能不同 | 用 `./install.sh --list` 看版本，两份保持同一版本最省事 |
| 本机既有个人副本，又装了插件 | 本地会同时出现 `/hq` 和 `/hq-orchestrator:hq`，模型可能选到任意一个；两份版本会慢慢不一致；插件版找辅助脚本时会先读 `~/.hq/skill-path`，可能用到个人副本里的旧脚本 | 二选一：只用插件就 `./install.sh --uninstall` 删掉个人副本；要在本地改插件、调试就保留，调试时明确用 `/hq` |

台账和运行记录（`.hq/`、`~/.claude/hq/runs/`）不受影响，两份 skill 写的是同一处。不确定本地是哪种安装时，运行 `./install.sh --list` 和 `ls ~/.claude/skills ~/.claude/plugins` 查看。

## 升级与卸载

先看已装的是哪个版本：`./install.sh --list` 会列出每个副本的路径和版本（读取副本里的 `.hq-install.json`）。然后按当初的安装方式升级：

| 安装方式 | 升级方法 |
|---|---|
| 一行脚本 | `curl -fsSL https://raw.githubusercontent.com/lostoy0/hq-orchestrator/v0.10.6/install.sh \| bash -s -- --update` |
| 一行脚本（已 clone 仓库） | `git pull` 后运行 `./install.sh --update`；项目范围加 `--scope project --project-dir <路径>` |
| Claude Code 插件 | `/plugin marketplace update hq-orchestrator-marketplace`，再在 `/plugin` 里更新 `hq-orchestrator`；本地路径添加的 marketplace 先在那个目录 `git pull` |
| Gemini 扩展 | `gemini extensions update hq-orchestrator` |
| `npx skills add` | 重新运行一次同样的命令覆盖 |
| 手动复制 | 拉取新版本后重新执行 `cp -r` 命令（会覆盖旧文件） |
| 项目内副本 | `./install.sh --update --scope project --project-dir <路径>`，然后提交 |

注意：

- `--update` 会把副本更新成**正在运行的这份脚本**的版本，不会自己联网查新版。所以一定要先拿到新版本的脚本（用新标签的一行命令，或先 `git pull`）。
- 新版本新增的技能（如 v0.6.0 的 `hq-plan`、v0.9.0 的 `hq-blueprint` 和 `hq-launch`）：`--update` 会补装到已更新 `hq` 的目录里。
- `--update` 只处理有安装记录的副本。v0.3 及更早装的、或手动复制的副本会被跳过并提示，用 `./install.sh --host <宿主> --force` 重装一次，以后就能正常 `--update`。
- `--update` **不更新子代理模板**（`--with-agents` 装的 `hq-t0…t4`）。新版本改了模板时（见 `CHANGELOG.md`），用原来的参数加 `--force` 重装：`./install.sh --host <宿主> --with-agents [--model-map '…'] --force`。`--force` 会覆盖你手动改过的模板。
- 升级后重开会话，宿主才会读到新技能。

**卸载**：`./install.sh --uninstall`（项目范围加 `--scope project --project-dir <路径>`）只删本脚本装过、有安装记录的副本。插件用 `/plugin` 卸载，Gemini 扩展用 `gemini extensions uninstall hq-orchestrator`。

---

## 复盘与数据

### 进化闭环：记录 → 复盘 → 改插件

1. **记录**：每个任务结束、每次运行结束，主会话往 `.hq/runs/<run_id>.jsonl` 追加一行（格式见 `metrics-schema.md`，记录 `host`；本地运行时另存一份到 `~/.claude/hq/runs/`，Codex 宿主也用这个目录）。成本以 `cost_usd` 为主，`tokens` 不含缓存读取。
2. **复盘**：累计约 5 次运行或 20 个任务时，主会话会提示你运行 `/hq-retro`。它用 `metrics.py` 出指标报告，先按 `CHANGELOG.md` 的验收指标核对上次改动，再交给独立子代理出有证据的建议（至少 3 个任务或 2 次运行出现才算）。只与本项目有关的经验直接写进 `.hq/PLAYBOOK.md`。上次改动是否达标，优先用 CHANGELOG 里的“验收判定”表达式由 `metrics.py --check-changelog` 按插件版本切分数据机器判定（带质量护栏）；报告还按版本、验证级别、规则标记（`flags`）和常驻推荐采纳率分组。
3. **改插件**：涉及插件本身的建议由你把关。报告最后附一段提示词，你复制到 hq-orchestrator 仓库的会话里执行，它会改文件、跑测试、在 `CHANGELOG.md` 记一条“待验证”并升补丁版本号。下一次复盘再验证它，没达标就撤回。

### 保存运行记录

PLAYBOOK 的 `runs_persist`：

| 取值 | 做法 | 适合 |
|---|---|---|
| `off` | 只写本地 `.hq/runs/`（本地运行另存 `~/.claude/hq/runs/`） | 只在本地用 |
| `branch` | 每批结束后 `runs-persist.sh save branch`：把记录写进专用分支 `hq/runs` 的 `runs/` 下并推送；只追加，多个会话同时写不冲突，不碰工作区和当前分支 | 云端（推荐；云端第一次运行结束时 `/hq` 会问你一次） |
| `commit` | `runs-persist.sh save commit`：只把记录文件提交到当前分支，随本批改动一起推 | 推不上 `hq/runs` 时自动降级到这里 |

`/hq-retro` 会先运行 `runs-persist.sh fetch` 把 `hq/runs` 上的记录取到 `.hq/runs-archive/`，再和本地记录一起汇总（同一次运行只算一次）。`hq/runs` 是独立的历史分支，不要合并进别的分支。

### 分享数据，帮助改进插件

完全自愿，不会自动上传：

1. 运行 `/hq-retro --export`。它用 `metrics.py --export-anon` 按白名单导出：只保留档位、模型、通道、用时、成本、通过率这类枚举和数字字段，删掉所有自由文本（任务标题、目标、备注、验证输出）和项目名，run_id 做哈希，时间只留日期。白名单见 `metrics-schema.md`。
2. 导出内容会完整显示给你，并保存到 `.hq/retro/export-<日期>.json`。
3. 愿意分享的话，用 [retro-data 模板](https://github.com/lostoy0/hq-orchestrator/issues/new?template=retro-data.md) 新建 issue 并贴上。issue 是公开的，贴之前请再看一遍。

`/hq-retro` 只会在第一次复盘的报告末尾提示一次这件事（记在 PLAYBOOK 的 `share_hint`），之后不再提。

---

## 支持的宿主

`SKILL.md` 只用抽象能力（spawn_worker、monitor 等），每个宿主的具体做法写在 `skills/hq/references/hosts/` 下。

| 宿主 | 宿主文档 | 状态 |
|---|---|---|
| Claude Code（本地 CLI、云端会话、桌面端、IDE） | `hosts/claude-code.md` | 主要宿主，v0.2 起实际使用 |
| Codex CLI | `hosts/codex.md` + `adapters/codex/` | agent 格式和目录已按官方文档核对；`codex exec` 和模型目录已实机核实，原生子代理**未实机运行** |
| **DeepSeek Harness（dsh）· DeepSeek 推荐路径** | `hosts/dsh.md` | 原生宿主：`subagent` 逐次指定 provider/model/思考深度；**只读过官方文档，未实机运行** |
| DeepSeek 后端 · 路径二：Claude Code 接 DeepSeek | `hosts/deepseek.md` | 档位压成 flash/pro 两档；云端子会话（B）仍用 Claude 模型 |
| DeepSeek 后端 · 路径三：Codex 接 DeepSeek | `hosts/deepseek.md` + `hosts/codex.md` | 配置示例来自官方摘要，待实测 |
| **OpenCode（V2）** | `hosts/opencode.md` + `adapters/opencode/` | 原生宿主：`hq-t0…t4` 子代理各带 `provider/model#variant`，档位逐任务生效；**只读过官方文档，未实机运行** |
| **Gemini CLI** | `hosts/gemini.md` + `adapters/gemini/` + `gemini-extension.json` | 原生宿主：`hq-t0…t4` 子代理各带 `model`（没有思考深度，只靠模型区分档位）；可作为 Gemini 扩展安装；**只读过官方文档，未实机运行** |
| Cursor | `hosts/generic.md` | 基础支持：技能目录按官方文档登记，**未实机运行**；有 shell 用 W 通道，否则**降级模式**（主会话按同样的计划、台账和质量门槛串行亲自执行）。原生子代理适配见 `docs/design-more-hosts.md` |
| 其他支持 SKILL.md 的工具 | `hosts/generic.md` | 同上；可用 `npx skills add` 安装 |
| Kimi（辅助执行者，不是宿主） | `hosts/kimi.md` | 经 W 通道承接 T0–T2 任务；**只按公开资料整理，未实机运行** |

## 设计要点

- **要不要编排**：编排有固定开销，小任务不开子会话。
- **并行以总用时为准**：优先缩短关键路径；小而相关的任务打包，大任务且文件不重叠才拆开。
- **难度分档**：按 `calibration.md` 5 维打分得到抽象档位 T0–T4，再按宿主映射成具体模型（Claude Code 为 haiku/low 到 opus/high）；选档算上失败重来的成本，看不准先调研。
- **拿不准就往上选**（`calibration.md` 规则 9）：Codex、dsh、DeepSeek 后端额度更便宜，上调一整档；Claude Code 默认只把思考深度上调一级，需求模糊或高风险时上调一整档（可在 PLAYBOOK 的 `cost_weight` 调整）。
- **档位只看难度、与并发数无关**（规则 11）：你说“尽量多开”、任务多、资源或额度紧张、遇到限流时，只会少开或排队，不会为多开而降模型或思考深度；只有你明确说“为了多开可以用低一点的模型”才降，且数据、安全、最高档任务和所有审核默认不降。
- **动态调档**：子会话遇到超范围衍生任务、难度超预期或反复失败时发检查点；卡住就升一档新开会话从分支接着做，不做降档交接。
- **运行位置路由**：需要本地资源的任务一定在本地跑，能并行的长任务放到云端，小任务在进程内执行。
- **资源保护**：每次派发前都检测资源，按 GREEN/YELLOW/RED 三级控制派发（读数读不到时报 UNKNOWN，按 YELLOW 最多再开 1 个）；给子会话限定构建并行度；RED 时停掉最新启动的重任务。
- **质量把关**：三项质量门槛；验证按风险分 doc/code/high/e2e 四级，只有 high 级主会话才逐个复跑验收命令，全量测试只在检查点跑；高风险或大改动另派独立审核者。
- **大批量任务按工作量分片**（`references/scale-out.md`，`scripts/scale.py`）：页面巡检、批量改文件这类同一种工作单元做很多遍的任务，按“单元数 × 单元耗时 + 启动开销”和单片目标时长（默认 40 分钟）算片数，不按模块数（例：600 页 × 1.5 分钟、并发上限 20 → 20 片、每片约 53 分钟，而不是 4 片各跑约 4 小时；上限不够时会请你提高）；共享工具先派前置会话改好，共享文件指定唯一归属。巡检时按 `HQ-PROGRESS` 进度行估剩余时间，掉队且剩余够多的再拆给新会话，快完成的不拆。
- **分层校验、批量合入**：子会话只跑类型检查和关联测试（改了共享基础文件才跑全量）；每次巡检把已交付的分片一起合入、一起校验一次，失败时定位到具体分片只处理那一片；全量测试攒到一批合入完、累计 N 片、推主干前这类检查点再跑。完成判定看 `## 交付` 小节和验证结果，不再搜“交付”两个字。
- **监控先做最小版本**：分片巡检只读进度行和最新事件，掉队或单元耗时普遍估错时提出再拆或重新规划，空转时发一次提醒；批末有严重或反复的问题就建议你跑 `/hq-retro`。阈值监控、限频分析、自动校准等更重的机制等有了真实运行数据再做（触发条件见 `references/scale-out.md`“推迟的功能”）。
- **可恢复**：所有状态写在台账里，上下文被压缩或会话重启后可以接着做。

## 仓库结构

```
插件与扩展清单
  .claude-plugin/plugin.json             Claude Code 插件清单（v0.10.6）
  .claude-plugin/marketplace.json        方便用 /plugin marketplace add 安装
  gemini-extension.json                  Gemini CLI 扩展清单：整个仓库可用 gemini extensions install 安装
  commands/*.toml                        Gemini 扩展的 /hq、/hq-retro 和各阶段命令（Claude Code 不读 .toml）

核心技能 /hq 与 /hq-retro
  skills/hq/SKILL.md                     核心流程：要不要编排 → 侦察 → 规划 → 选档 → 选位置 → 控并发 → 派发 → 监控与调档 → 审核归并 → 记录数据 → 汇报
  skills/hq/calibration.md               选档校准表：5 维打分、T0–T4 档位、修正规则（复盘只调这个文件）
  skills/hq-retro/SKILL.md               /hq-retro 复盘：验证上次改动、出有证据的建议、生成改插件的提示词

阶段技能
  skills/hq-research/                    竞品调研（template.md 是报告格式）
  skills/hq-prd/                         需求文档（template.md 是文档格式）
  skills/hq-design/                      设计规范和高保真可点击原型（prototype-starter/ 是原型起步套件）
  skills/hq-arch/                        架构设计、详细设计和决策记录（diagram-style.md 是画图规范）
  skills/hq-plan/                        版本计划和任务清单（带预估档位）
  skills/hq-blueprint/                   一键把各阶段串起来跑完
  skills/hq-launch/                      上线检查：46 项清单、结论、起草上线材料

参考文档（skills/hq/references/）
  runtimes.md                            抽象能力、派发通道（A/B/C/D/W）通用规则和宿主索引
  scale-out.md                           大批量任务：按工作量分片、共享工具与归属、掉队再拆、分层校验、批量合入；推迟的功能及触发条件
  hosts/*.md                             各宿主的能力表、档位映射、安装调用、待核实项；kimi.md 为辅助执行者
  brief-template.md                      子会话任务说明模板（含验证级别、检查点）与交付格式
  metrics-schema.md                      运行数据格式（JSONL，v1）和用量口径
  playbook-template.md                   项目经验手册 .hq/PLAYBOOK.md 的模板（含授权配置）
  roles/*.md                             角色卡（产品、设计、架构、开发、测试、安全、研究、运维、法务、运营增长、商务）
  stages/common.md                       阶段技能通用规则：产物目录、编号与追溯、模式、评审协议、决策优先级
  backlog-schema.md                      计划清单 backlog.json 的格式

脚本（skills/hq/scripts/）
  resources.sh                           资源探测（Linux/cgroup/macOS），输出还能新开几个本地任务
  cli-worker.sh、backends/*.sh           W 通道：在独立 git worktree 里后台运行各 CLI；每个 CLI 一个后端文件
  assist-config.py                       辅助执行者配置：读 codex 模型目录、推荐档位、写用户级或项目配置、校验
  metrics.py                             把运行数据汇总成指标报告（只读）；--export-anon 按白名单脱敏导出
  scale.py                               分片规则的可执行版：片数、掉队与重新规划、交付判定、测试范围、合入分组、失败定位
  runs-persist.sh                        把运行记录保存进仓库（专用分支 hq/runs 或当前分支）并取回
  backlog-check.py                       计划清单检查（只读）：编号、依赖、档位与分数、需求覆盖、暂缓任务、关键路径
  doc-check.py                           需求文档、竞品调研报告、架构文档、上线清单检查（只读）
  prototype-check.py、prototype-walk.mjs 可点击原型的静态检查和自动走查（走查需要 Playwright；都支持接管外来格式的原型）
  stage-status.py                        列出各阶段产物的状态（齐不齐、检查结果、是否过期），只读
  fetch-page.py                          用 curl 走会话代理抓取网页正文（宿主自带的抓取工具打不开时用）

适配器与安装
  install.sh                             一键安装：自动检测工具、按最小目录集合复制技能，支持 --list/--update/--uninstall
  adapters/hosts.tsv、skill-dirs.tsv     宿主登记表和技能目录登记表（新增宿主加一行）
  adapters/tiers.tsv、render.sh          档位登记表和模板生成脚本（子代理模板的唯一来源）
  adapters/agent-dirs.tsv                子代理模板的安装目录登记表
  adapters/codex/、opencode/、gemini/    各宿主的 hq-t0…hq-t4 子代理模板（生成）

文档、测试与仓库管理
  PROMPT.md                              不装插件时直接粘贴用的精简提示词
  CHANGELOG.md                           每条改动的原因、验收指标和验证状态
  docs/design-stages.md                  阶段技能设计草案和路线图
  docs/design-more-hosts.md              支持更多宿主的设计草案与路线
  tests/                                 各脚本的自测（假 CLI 在 tests/fixtures/）
  .github/                               issue 模板、PR 检查清单、CI（Linux 和 macOS 跑全部自测）
  LICENSE、CONTRIBUTING.md、SECURITY.md  许可、贡献指南、安全问题报告方式
```

## 自测

```bash
for t in tests/test_*.sh; do bash "$t" || echo "FAILED: $t"; done
python3 -m unittest discover tests
```
- `test_cli_worker.sh` 用 `tests/fixtures/fake-cli/` 下的假 `codex`、`claude`、`opencode`、`gemini`、`cursor-agent` 测参数拼接和用量解析，不调用真实 CLI。
- `resources.sh` 支持 `HQ_FAKE_CORES`、`HQ_FAKE_LOAD1`、`HQ_FAKE_MEM_TOTAL_MB` 等环境变量注入模拟读数，用来覆盖 GREEN/YELLOW/RED 各种情况；`HQ_FAKE_UNREADABLE=cores,mem_total,…` 模拟读不到的读数（UNKNOWN）。

## 待核实项与本机验证清单

本仓库的开发环境装不了 dsh 等工具，下面这些需要你在本机实测。结果请写进项目 `.hq/PLAYBOOK.md`（宿主映射）或提 issue。

**待核实**（详见各宿主文档第 5 节）：
- Codex：agent 模板实际能否被加载；并发上限配置名；`codex cloud` 能否指定 model/effort；原生子代理的监控、中止和用量读取。
- dsh：桌面端子代理模型路由设置的位置；并发上限配置键；非交互 CLI 命令（能否做 W 通道 worker）；`reasoning_effort` 取值范围；用量和成本的读取方式；中止子代理的方式；Schedule 的工具名。
- DeepSeek（路径二、三）：`CLAUDE_CODE_EFFORT_LEVEL=max` 是否覆盖 hq 按档位设的 effort；`ANTHROPIC_DEFAULT_OPUS_MODEL` 能否设为 `deepseek-v4-pro`；`deepseek-flash` 与 `deepseek-v4-flash` 是否等价。
- Claude Code：本地 CLI 发起云端任务（通道 D）的参数。
- OpenCode：`hq-t*` 子代理能否被识别、各档 `model#variant` 能否解析；中止子代理的方式；`opencode session export` 里的 token/成本字段；多个后台子代理同时运行时的权限审批。
- W 通道后端：`opencode run`、`gemini -p`、`cursor-agent -p` 在本机各跑一次 `start/status/usage/stop`，核对参数是否被接受、`usage` 是否有 tokens（cursor 的用量字段名未知）；gemini `auto_edit` 下能否跑 shell 命令。
- Gemini CLI：`gemini extensions install` 能否装上、`/hq` 能否激活技能；`hq-t*` 子代理能否加载、模型能否生效；同一轮多个子代理调用能否并行；子代理用量的读取方式；Claude Code 装插件后 `commands/*.toml` 不应出现为命令。
- Cursor、Gemini CLI：`--host auto` 装好后各工具能否发现并触发 hq 技能；Cursor 是否也读 `~/.agents/skills`；`npx skills add` 是否带上 `scripts/` 和 `references/`。

**Codex 冒烟测试**：
```bash
codex --version
./install.sh --host codex --with-agents --model-map auto                       # 按本机模型目录生成 ~/.codex/agents/hq-t*.toml
echo "只回复 OK" | codex exec -m <模型> -c model_reasoning_effort=low -s read-only --json - | tail -3   # 看 turn.completed 的 usage 字段
cd <某个 git 仓库> && echo "列出仓库根目录文件" > /tmp/b.md
bash <路径>/cli-worker.sh start --id smoke --cli codex --model <模型> --effort low --brief /tmp/b.md --sandbox read-only
bash <路径>/cli-worker.sh status --id smoke; bash <路径>/cli-worker.sh usage --id smoke   # tokens 不应为 null
```
在 codex 里让它列出可用 agent，确认 hq-t0…hq-t4 被识别。

**dsh 跑一次小任务**（DeepSeek 路径一，推荐）：`./install.sh --host dsh`（或已装 codex 则跳过），然后：
- 在桌面端开启子代理模型选择；
- 运行 `list_subagent_models`，按 `hosts/dsh.md` 第 3 节把 T0–T4 映射到返回的路由，写进 `.hq/PLAYBOOK.md`；
- 运行 `/hq` 跑一个小任务（一个 T0、一个 T3），核对子代理实际用的模型和思考深度与档位映射一致，并记下用量能否读到。

**DeepSeek 后端跑一次小任务**（路径二）：按 `hosts/deepseek.md` 设好环境变量，在一个小仓库里运行 `/hq` 做一个 T0 任务和一个 T3 任务，然后核对：
- 子代理实际用的模型：T0 应为 flash，T3 应为 pro（`CLAUDE_CODE_SUBAGENT_MODEL` 不要设）；
- effort：分别在设与不设 `CLAUDE_CODE_EFFORT_LEVEL=max` 时各跑一次，比较用时和用量，判断档位的思考深度是否被覆盖；
- 用量：`.hq/runs/*.jsonl` 的 tokens 与 DeepSeek 控制台账单是否对得上（cost_usd 按 Claude 价格算，不可信）。

## 已知限制

- Codex 原生子代理、dsh、DeepSeek 后端以及 OpenCode/Cursor/Gemini CLI 都还没有实机运行数据，见上一节。Cursor 目前只是基础支持，档位不生效；OpenCode、Gemini CLI 的子代理和主会话共用工作目录，改代码的任务靠 hq 先建 worktree 隔离。
- 本地 CLI 能否直接创建云端子会话，取决于 CLI 版本（见 runtimes.md 的通道 D）。这类子会话监控能力较弱。需要强监控时，把主会话放在云端，再通过“连接电脑”处理本地任务。
- 进程内子代理和主会话共享同一台机器，资源保护只能控制派发节奏，没法限制子代理自己调用的进程。所以任务说明里的并行度限制很重要。
- 进程内子代理的返回结果只有 token 总数、分不出缓存读取，这类任务的 `tokens` 记为空，成本比较以云端子会话的 `cost_usd` 为主。
- 难度分档表是经验默认值，可以按你的账户和实际体验在 `skills/hq/calibration.md` 里调整；更推荐用 `/hq-retro` 按数据调整。

---

## 许可与商用

本项目以 [Apache License 2.0](LICENSE) 加 [Commons Clause](https://commonsclause.com/) 条件授权。下面是通俗摘要，**以 [LICENSE](LICENSE) 正文（英文）为准**。

- **任何人都可以免费使用**：个人、公司内部、商业项目都行。可以修改，也可以免费再分发，分发时保留许可文本和版权声明，并带上 Commons Clause 条件。
- **不可出售**：不得把本项目（或基于它的衍生品）打包出售，也不得收费提供价值主要来自本项目的产品或服务，包括收费的托管、咨询和技术支持。
- **作者不受此限**：作者自己可以出售、上架插件或技能市场、收费提供技术支持。想合作或购买服务，请在 [Issues](https://github.com/lostoy0/hq-orchestrator/issues) 联系作者。
- **不是 OSI 意义上的“开源”**：因为有上面的限制，本项目属于源码公开（source-available）。

参与贡献见 [CONTRIBUTING.md](CONTRIBUTING.md)，安全问题见 [SECURITY.md](SECURITY.md)。
