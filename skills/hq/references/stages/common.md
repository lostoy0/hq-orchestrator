# 阶段技能通用规则

适用于 `/hq-plan` 及以后的 `/hq-research`、`/hq-prd`、`/hq-design`、`/hq-arch`。每个阶段技能只写本阶段的任务图、产物和完成标准，其余按本文件和 `../../SKILL.md`（hq 主流程）执行。

## 1. 和 hq 主流程的关系

- 阶段运行就是一次 hq 运行：照常生成 `run_id`、建台账、侦察、选档、派发、审核、记录数据、汇报。铁律全部适用，主会话不亲自写长文档，交给子会话。
- 台账头部加一项 `stage: <阶段名>`；run 记录加第 8 节的可选字段。
- 第 0 步照常判断：产物很小（例如只补一两项）时主会话直接做，评审仍按第 5 节至少做 1 轮。
- 产物改动和代码改动一样，走 `hq/<任务id>` 分支，按 PLAYBOOK 授权合并。

## 2. 产物目录

- 根目录 `docs_root`：先看 PLAYBOOK“项目事实”里的 `docs_root`，再看已有的对应表 `hq-artifacts.json`（第 10 节）；都没有时，项目已有 `docs/`、`doc/`、`documentation/`、`.opc/`、`specs/` 之一就沿用，否则用 `docs/`。定下后写进 PLAYBOOK。
- **项目里已经有需求、设计、架构、计划之类的文档时（不管放在哪、什么格式），先按第 10 节接管，不要在 `docs_root` 下从头再写一套。**
- 目录约定（项目已有等价文件时沿用原路径，写进对应表）：

```
<docs_root>/
  product/brief.md          一页纸：想法、目标用户、要解决的问题（输入不足时由阶段技能生成）
  product/prd.md            需求文档（/hq-prd）
  research/competitors.md   竞品调研（/hq-research）
  design/design-system.md   设计规范（/hq-design）
  design/screens.md         页面与流程说明（/hq-design）
  design/prototype/         可点击原型，manifest.js 是页面、账号、流程清单（/hq-design）
  design/screens/           原型走查截图（/hq-design）
  tech/architecture.md      架构设计（/hq-arch）
  tech/detailed-design.md   详细技术设计（/hq-arch）
  tech/adr/NNNN-<名>.md     架构决策记录
  plan/roadmap.md           版本计划（/hq-plan）
  plan/backlog.json         计划清单，给 /hq 读（/hq-plan，格式见 ../backlog-schema.md）
  launch/checklist.md       上线检查（/hq-launch），同目录还有运维手册、发布说明、运营计划和 legal/ 下的法律文本草稿
  blueprint.md              项目蓝图索引（/hq-blueprint）
  reviews/<阶段>-<YYYYMMDD>.md  评审记录
```

- Markdown 产物开头写元数据（项目已有的文档没有元数据时，补在开头，不改正文）：

```yaml
---
hq_stage: plan
version: 1            # 每次实质修改加 1
based_on: [prd@3, architecture@2]   # 依据的上游产物及版本；上游没有版本号时写文件的提交 sha 前 7 位
status: draft         # draft | reviewed | approved（approved 只由用户设定）
updated: 2026-11-26
---
```

- **过期**：运行开始时比较 `based_on` 和上游当前版本。上游变了，本产物视为过期：本次运行先对齐变化的部分，汇报里写明对齐了什么。

## 3. 编号与追溯

| 前缀 | 含义 | 定义在 |
|---|---|---|
| `F-001` | 功能需求 | prd.md |
| `NFR-001` | 非功能需求（性能、安全、可用性、合规） | prd.md |
| `P-01` | 页面或界面 | design/ |
| `M-01` | 模块或服务 | architecture.md |
| `ADR-0001` | 架构决策 | tech/adr/ |
| `R1` | 版本（迭代） | roadmap.md、backlog.json |
| `B-001` | 计划任务 | backlog.json |
| `A-01` | 假设 | 各产物的“假设与待确认”一节 |
| `D-01` | 待用户决定的事项（第 6 节） | 各产物的“假设与待确认”一节 |
| `C-01` | 竞品 | research/competitors.md |
| `S1` | 来源（链接和访问日期） | 各产物的“来源”表 |

- 下游引用上游编号（任务写它实现哪些 `F-`，页面写它服务哪些 `F-`），编号一经发布不复用；删掉的写“已废弃”。
- 上游用了自己的编号（如 `REQ-001`、`NFR-01`、`LC-01`、`PG-001`）：下游照用原编号，不换成 `F-001`；对应表里记下前缀（第 10 节）。各检查脚本只要求“大写前缀-编号”的形状。
- 上游完全没有编号时（例如用户自己写的需求文档）：下游在自己的产物里建一张“需求索引”（编号、标题、出处），不改上游文件；汇报里建议用户运行对应阶段补上编号。

## 4. 模式

- **新建**：产物不存在。
- **补全**（产物已存在，默认）：先派只读子会话按本阶段完成标准逐条检查，列出缺项和问题，再按缺项派写作任务。只增改，不删除用户写的内容；用户内容和标准冲突时，保留原文，在“假设与待确认”里写明冲突和建议。
- **只评审**（`--review-only`）：只做检查和第 5 节的评审，产出评审记录，不改产物。
- **接管**（已有产物不是本阶段模板的格式，即对应表里的 `foreign`）：按第 10 节做内容评审、补缺口，不改写成本模板的格式。

## 5. 评审协议

**评审团**：每个阶段技能给出默认评审角色（2–4 个），`--panel` 可以改。角色卡见 `../roles/<角色>.md`。

**派发**：每个评审者一个只读子会话，并行。说明里只给：角色卡全文、产物路径、上游产物路径、本阶段完成标准、下面的意见格式；**不给作者的思路和自评**。评审者把完整意见写进 `.hq/reviews/<阶段>-<角色>.md`（`.hq/` 不提交），交付里只给条数和 blocker 摘要，主会话分诊时再读文件，避免几份长意见撑满主会话的上下文。评审子会话的档位按 `calibration.md` 打分，风险和验证难度按产物的影响评，一般不低于 T2。开了辅助执行者时，可以把其中一个评审派给辅助（审核类任务的档位规则不变，见 `calibration.md` 规则 10）。

**意见格式**（每人最多 10 条，按严重程度排序，次要问题能合并就合并）：

```
- id: <角色缩写>-<序号>，如 qa-3
  severity: blocker | major | minor
  ref: <编号或完成标准条目，如 F-012、完成标准 4>
  issue: <问题，一两句>
  evidence: <依据：产物位置、上游原文、清单条目>
  fix: <建议改法>
```

- `blocker`：违反完成标准、和上游需求冲突、违反安全或合规底线、按现状实现不了。
- `major`：明显影响用户体验、成本或可维护性，而且有更好的做法。
- `minor`：措辞、风格偏好、锦上添花。

**分诊**（主会话做，结果写进评审记录）：每条标 `accept`、`reject`（必须写理由，理由按第 6 节的优先级）、`defer`（进待办或下一版本）。`minor` 默认 `defer`，改动很小的直接 `accept`。

**修改**：把 `accept` 的意见交给作者子会话（或新开一个，说明里附产物和意见原文）修改。

**轮次**：
- 第 2 轮只派第 1 轮提过 `blocker`、`major` 的评审者，只核对这些意见是否改好、驳回理由是否成立；不接受新意见，除非是这次修改引入的新 `blocker`。
- 默认最多 2 轮（`--rounds` 可改，上限 3）。
- **收尾条件**：没有未解决的 `blocker`。到了轮次上限还有未解决的 `blocker` 或有争议的驳回，写进产物的“假设与待确认”，汇报时交给用户，不再开新一轮。

**评审记录** `reviews/<阶段>-<YYYYMMDD>.md`：评审团和档位、每轮的意见（含分诊结果和理由）、最终未解决项。

## 6. 决策

**优先级**（PLAYBOOK“授权”区 `product_priorities` 可以改顺序）：
1. 合规与安全底线（不触碰就不比较）
2. 核心用户价值与体验
3. 商业可行性（收入模式、获客、留存）
4. 技术简单、可维护、和现有代码一致
5. 成本与速度

两个方案难分高下时，选更容易撤回、首个版本更小的那个。每个决策在台账“决策”区记一行。

**要用户决定的事项**：除了 hq 主流程的停止条件，下面这些改不回来的决定由用户拍板：
- 商业模式和定价的根本选择（免费 / 订阅 / 一次性付费 / 广告，目标价位区间）；
- 品牌和产品命名；
- 目标市场和目标人群的选择（不同选择会推翻大部分需求时）；
- 法务或合规风险（处理敏感个人信息、未成年人、金融医疗、跨境数据、需要资质的业务）；
- 需要真实付费、注册外部账号或联系真实的人。

文档本身是能改回的，所以这些事项**不阻塞写作**：按推荐选项先写，在“假设与待确认”里记一条 `D-xx`（问题、选项、推荐和理由、改选其他项时要改的章节），依赖它的内容写成容易替换的形式。阶段结束时在汇报里一次性问；有未决的 `D-xx` 时，产物的 `status` 不能改成 `approved`。真正要执行的动作（付费、注册账号、联系真实的人、对外发布）仍按 hq 停止条件，没有授权就不做。
- 带 `--ask` 时，`D-xx` 在侦察后、写作前先问一次，等用户回答再写。

其他不确定的地方：选最合理的做法继续，在产物的“假设与待确认”一节写一条 `A-xx`（假设、依据、猜错的影响）。阶段结束时在汇报里一次性列出，每条附推荐选项；用户不回复也不阻塞下一阶段。

## 7. 联网与来源

需要外部信息的阶段（`/hq-research`，以及 `/hq-prd` 里的竞品速览）遵守：
- **联网能力**：侦察时确认主会话和要派的子会话能联网：宿主有联网搜索或网页抓取工具；或者 shell 能访问外网，可以用 `curl` 取公开页面。W 通道的 CLI worker 不一定能联网，联网任务不派给它，除非先验证过。都不能联网时，按各阶段技能的“不能联网”规则处理，**不凭模型记忆冒充调研结果**。**能搜索但打不开网页原文**（网络策略只放行了搜索）也算不能联网：搜索摘要不是来源，不能据此写结论；侦察时先用一个来源实际抓取一次确认，**而且要用子会话实际会用的同一个工具验证**：宿主自带的网页抓取工具（如 WebFetch）不一定走会话的网络代理，`curl` 能打开不代表它能打开。打不开时让子会话改用 `python3 <hq>/scripts/fetch-page.py <URL> [字数]`（用 curl 走代理，输出标题和正文纯文本；退出码 3 表示连不上，1 表示空页面或 HTTP 错误，都不能当来源）。
- **来源**：每条事实性结论（价格、功能、用户数、融资、评分、发布时间）后面标来源编号 `[S3]`，文末“来源”表写编号、标题、链接、访问日期。推断和估算写成“推断：…”，并给出依据的来源。找不到来源的不写，或者写“未找到公开信息”。
- **数字**：写清口径和时间（“2026-11 官网定价页，按年付”）。不同来源冲突时都列出来，不自己挑一个。
- **边界**：只用公开信息；不登录别人的账号、不绕过付费墙或反爬、不抓取个人信息；遵守网站条款。需要注册试用的产品，只写公开资料能确认的部分，把“建议注册试用确认”记进待确认。

## 8. 运行记录（可选字段，写在 run 记录里）

| 字段 | 含义 |
|---|---|
| stage | 阶段名：`plan`、`prd`、`research`、`design`、`arch`、`launch`、`blueprint`（`blueprint` 另记 `stages_run`：实际跑了哪些阶段） |
| stage_mode | `create` / `complete` / `review_only` |
| review_rounds | 实际评审轮数 |
| review_findings | `{blocker, major, minor, accepted, rejected, deferred, unresolved}` 各几条 |
| open_assumptions | 交给用户的“假设与待确认”条数 |

`metrics.py` 目前忽略这些字段；样本够了以后再加汇总（见 `docs/design-stages.md` 第 8 节）。

## 9. 机械检查

能用脚本检查的完成标准都用脚本检查，结果写进评审记录：计划清单用 `scripts/backlog-check.py`，需求文档和竞品报告用 `scripts/doc-check.py prd|research <文件>`，架构文档用 `scripts/doc-check.py arch <architecture.md> --detailed <detailed-design.md> --prd <需求文档>`，原型用 `scripts/prototype-check.py`（静态）和 `scripts/prototype-walk.mjs`（需要 Playwright，逐页逐状态截图并执行流程），上线检查用 `scripts/doc-check.py launch <checklist.md>`。`scripts/stage-status.py --docs <docs_root>` 一次列出所有阶段产物的状态（齐不齐、检查有没有错误、依据的上游是否已更新），`/hq-blueprint` 用它决定跑哪些阶段。脚本报错误时先修再评审，不要把格式问题留给评审者。

## 10. 接管已有产物

真实项目常常已经有文档：别的工具生成的（如 `.opc/` 下的一整套）、团队自己的模板、旧版本的需求文档。阶段技能遇到它们时**接管**，而不是重写。

**1. 发现**（侦察时做）：运行 `python3 <hq>/scripts/stage-status.py --discover --root <仓库根目录>`。它按路径和文件名在全仓库找各阶段的文档（跳过 `node_modules`、`.git` 等，评审记录目录不算），给出一份建议的对应表：每个阶段的路径、格式（文件开头有 `hq_stage` 元数据的算 `hq`，否则 `foreign`）、是否已冻结（开头 30 行里写了“已冻结”“frozen”“status: approved”等）。侦察任务核对这份建议：删掉找错的、补上漏掉的（比如没被认出的原型目录）、确认冻结状态，然后写成 `<docs_root>/hq-artifacts.json`，和文档一起提交（不要放在不提交的 `.hq/` 里）。

```json
{
  "schema": "hq-artifacts/1",
  "docs_root": ".opc",
  "stages": {
    "prd":    {"format": "foreign", "paths": [".opc/product/prd.md"], "frozen": true, "id_prefixes": ["REQ", "NFR", "LC"]},
    "design": {"format": "foreign", "paths": [".opc/product/prototype"], "frozen": false},
    "arch":   {"format": "foreign", "paths": [".opc/tech/design.md", ".opc/tech/adr", ".opc/tech/contracts"], "frozen": false},
    "plan":   {"format": "foreign", "paths": [".opc/plan/v1.1-standard.dag.yaml"], "frozen": false}
  }
}
```

- `paths` 写相对仓库根目录的路径，可以是文件或目录；没列出的阶段按 hq 格式放在 `docs_root` 下。
- `hq` 格式的阶段只是换了位置时，写 `{"format": "hq", "paths": {"prd": "product/requirements-v2.md"}}`（相对 `docs_root`，键名同 `stage-status.py` 里的产物名）。
- `id_prefixes`：这个阶段的编号前缀，下游照用。

**2. 接管评审**（代替这个阶段的“新建”）：按本阶段的完成标准逐条判断**内容**是否满足，不看格式和章节名。
- 派该阶段默认的评审团（只读），说明里给：对应表里的文件、本阶段完成标准、第 5 节的意见格式，**以及已经存在的下游产物**（例如评审需求时附上技术设计和契约）：评审者先查下游是否已经解决，已解决的只记“上游缺验收标准”，不报 blocker。每个评审者多交一张表：完成标准每条一行，写“满足 / 部分满足 / 缺失”和依据（文件和位置）。
- 原型检查脚本有外来格式模式（目录里没有 `manifest.js` 时自动进入，也可加 `--foreign`），接管评审和补缺口时都要跑，结果写进评审记录：`python3 <hq>/scripts/prototype-check.py <原型目录> --prd <需求文档>`（本地链接和资源都存在、没有外部网络资源；需求文档里的编号在哪个 HTML 里都没出现时给警告，只是覆盖信号，不算证据）；`node <hq>/scripts/prototype-walk.mjs <原型目录> --out <截图目录> --script .hq/prototype-flows.mjs`（逐页打开并跟着页内 `#` 路由走，记录控制台报错、页面异常、失败请求和 HTTP ≥400，页面文字出现 `[object Object]`、`undefined`、`NaN` 时给警告）。不带 `--script` 的走查只是冒烟（不登录、不切状态和角色），评审记录里照此写明，不要当成状态和流程都验过。需求编号缺得多时按前缀分组显示；在 HTML 里标出需求级编号（如 `REQ-xxx`）、或用 `--id-prefixes` 只看需求级，能消掉大部分噪音。原型自己的状态切换和核心流程写成项目脚本（默认导出 `async ({ page, baseUrl, step, check, shot }) => {}`，格式见 `/hq-design` 的 `prototype-schema.md`），存在 `.hq/` 下反复用，不要每次重写一套走查。
- `doc-check.py`、`backlog-check.py` 仍然只认 hq 格式，接管时不跑；能用的通用验证照做（如对照需求核对计划覆盖）。
- 主会话分诊后写评审记录 `<docs_root>/reviews/<阶段>-audit-<YYYYMMDD>.md`，然后运行 `stage-status.py --docs <docs_root> --record-audit <阶段> --report <评审记录路径> --blockers <未解决的 blocker 数> --majors <数>`。脚本会记下文件指纹：之后文件一改，这个阶段就回到“待接管评审”。

**3. 补缺口**：
- **已冻结的产物不改**。缺口写成提案 `<docs_root>/reviews/<阶段>-proposals-<YYYYMMDD>.md`（每条：问题、依据、建议怎么改、影响哪些下游），交给用户决定；用户同意后再按下一条改。blocker 也只写提案，汇报时醒目列出。
- `stage-status.py` 的判断：已冻结的阶段只要没有 blocker 就算完成（major 是提案）；没冻结的阶段有 blocker 或 major 都算“需要修改”，补完重新评审后才算完成。
- **没冻结的产物**：在原文件里、按原文件自己的结构和编号补（加条目、补验收标准、补状态说明），只增改不删除；改完重新做第 2 步的评审（指纹变了）。
- 不把外来格式整份改写成本模板的格式，除非用户明确要求（参数 `--convert`）；那时新文件写到 hq 默认位置，原文件不动，对应表改指向新文件。

**4. 下游怎么用**：下游阶段把外来格式的上游当作正常输入读（按内容理解，编号照用）；需要机器可读的上游（如 `/hq --backlog` 要的计划清单）时，由对应阶段技能做转换，见 `/hq-plan` 的“导入”。
