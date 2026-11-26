# 更新记录

## 格式说明

按版本倒序。每个版本下面，**每条改动**都写这五项：

- **改动**：改了什么（到文件和段落）。
- **原因/假设**：为什么改；预期会带来什么变化。
- **验收指标**：之后用哪项指标、达到什么数值才算有效（来自 `skills/hq/scripts/metrics.py` 的报告）。
- **状态**：`待验证` / `已验证` / `已撤回`。
- **复盘报告**：对应的 `.hq/retro/<日期>.md`；没有就写“无（人工改动）”。

规则：

- 新改动一律先标“待验证”。`/hq-retro` 用验收指标核对后，才改为“已验证”或“已撤回”。
- 撤回时保留原条目，只改状态，并在原因里写撤回理由，不要删除。
- 改动不能以牺牲质量门槛（不漂移、验证到位、问题少）换取省钱。返工率或问题数上升的改动要撤回。

---

## 未发布

## v0.10.1（2026-11-26）

### 调研抓取：新增 fetch-page.py，验证用子会话会用的同一个工具
- **改动**：新增 `skills/hq/scripts/fetch-page.py`（用 curl 走会话代理抓取公开网页，输出标题和正文纯文本，去掉脚本和导航短行；退出码 0 成功、1 空页面或 HTTP 错误、2 参数错误、3 连不上）和 `tests/test_fetch_page.py`（本地 HTTP 服务测试）。`stages/common.md` 第 7 节：侦察时要用子会话实际会用的同一个工具验证能否打开网页，宿主自带的抓取工具打不开时改用 fetch-page.py。`/hq-research` 第 2 节同步。
- **原因/假设**：在一个真实项目上做竞品调研时，网络放行后 `curl` 能打开来源，但宿主的 WebFetch 不走会话代理，5 个调研子会话全部报域名解析失败（它们没有用搜索摘要冒充来源，按规则交回）。改用 curl 脚本后，5 个子会话共核对 42 篇原文，其中还排除了一篇注明“由 AI 生成”、数字与其他来源冲突的文章。
- **验收指标**：联网调研中因抓取工具打不开而整轮失败的次数 = 0；调研报告里的来源都能用 fetch-page.py 重新打开（研究员抽查时）。
- **状态**：待验证（自测通过；已在真实项目的调研中使用）
- **复盘报告**：无（人工改动，来自实测）

---

## v0.10.0（2026-11-26）

接管已有产物：项目里已经有别的工具或团队自己格式的文档时，阶段技能接管它们，而不是另起一套。来自一个真实项目的实测。

### 接管已有产物（发现、接管评审、冻结保护、计划导入）
- **改动**：`stage-status.py` 新增 `--discover`（按路径和文件名在全仓库找各阶段文档，建议对应表，识别是否已冻结，`adr/`、`contracts/`、`prototype/` 这类目录整体作为产物）、读取 `<docs_root>/hq-artifacts.json`（`hq-artifacts/1`：每个阶段的格式 `hq | foreign`、路径、是否冻结、编号前缀、评审记录）、外来格式阶段的状态 `unaudited`、`--record-audit`（写入评审结果和文件 sha256 指纹，文件改动后回到 `unaudited`）、hq 格式阶段的路径覆盖、`skip`（如导入的计划不需要 `roadmap.md`）、`source` 和 `--record-source`（从别的文件转换来的阶段在来源改动后标为过期）。`backlog-check.py` 的编号只检查形状（大写前缀-编号），接受 `REQ-001`、`NFR-01`、`DF-V1-BASE01`、`M1` 等；需求文档里遗漏编号的检查按清单里的前缀加 `F`、`NFR` 扫描。`stages/common.md` 第 2 节 `docs_root` 认 `.opc/`、`specs/`，已有文档时必须先接管；第 3 节编号照用；第 4 节加“接管”模式；新增第 10 节“接管已有产物”（发现、对应表、接管评审、补缺口：冻结的只写提案、没冻结的在原文件里按原结构补，`--convert` 才改写格式）。`/hq-prd`、`/hq-design`、`/hq-arch`、`/hq-research` 的输入表改为接管，新增 `--convert`；`/hq-plan` 新增第 6 节“导入已有计划”和 `--import`；`/hq-blueprint` 侦察时先发现、`unaudited` 阶段只做接管评审或导入、冻结产物有 blocker 时停下交给用户；`/hq-launch` 按内容读外来格式的需求。`backlog-schema.md`、README 中英文、`docs/design-stages.md` 同步。测试：`tests/test_stage_status.py` 新增发现、接管生命周期、路径覆盖、导入计划的 `skip` 和 `source`；`tests/test_backlog_check.py` 新增外来编号。
- **原因/假设**：在一个已有文档的真实项目上实测，`.opc/` 下已有另一套工具生成的完整产物（已冻结的需求 v1.1、可点击原型、技术设计和 6 条 ADR、接口契约、带难度分级的任务图），但阶段技能只认自己的目录和格式：会在 `docs/` 下全部重做，需求检查判成 0 个功能，需求阶段会另写一份已冻结的需求，计划无法被 `/hq --backlog` 执行。真实项目大多已有文档，接管应是默认行为。
- **验收指标**：在已有文档的项目上运行 `/hq-blueprint`，新建的、和已有文档重复的阶段产物数 = 0；对已冻结文档的改动数 = 0（只有提案）；导入的计划经 `backlog-check.py` 0 错误，任务数与原计划一致。
- **状态**：待验证（自测通过；PR #31 的 CI 在 ubuntu 和 macOS 上全部通过；已在一个已有文档的真实项目上运行：发现、接管评审、冻结保护、计划导入均按设计生效，导入的 92 个任务与原计划逐项一致）
- **复盘报告**：无（人工改动，来自实测）

---

### 实测后的修正（同一真实项目上跑完 /hq-blueprint）
- **改动**：`common.md` 第 10 节：接管评审上游阶段时把已有的下游产物一并给评审者，下游已解决的只记“上游缺验收标准”；`stage-status.py` 对没冻结的外来格式阶段，评审有 major 时状态为 `needs_work`（冻结的阶段 major 只是提案）；`/hq-blueprint`：接管评审都是只读的，不受阶段关卡限制，可一次并行评审全部 `unaudited` 阶段；`backlog-check.py`：清单有 `imported_from` 时，超过 120 分钟的警告合并成一条，`/hq-plan` 导入时写这个字段、保留原计划粒度；`common.md` 第 7 节：能搜索但打不开原文也算不能联网；第 5 节：评审者把完整意见写进 `.hq/reviews/`，只回摘要；`stage-status.py --discover` 识别“vX 已确认”为已冻结。测试同步。
- **原因/假设**：实测中：需求评审把技术设计已解决的支付验签、后台分权报成 blocker，主会话核对后才降级；原型没冻结、22 条 major 未补却显示“已完成”；关卡停下后架构没有评审，用户拿到的问题不完整；导入的 92 个任务产生 78 条相同警告；运行环境只放行搜索，调研子任务只拿到摘要；7 份长评审意见占满主会话上下文。
- **验收指标**：接管评审中被主会话降级的 blocker 占比 ≤ 20%；一次 `/hq-blueprint` 结束时所有已有阶段都有评审记录（停在关卡的除外写作）；主会话上下文因评审意见触发压缩的次数 = 0。
- **状态**：待验证（自测通过；PR #31 的 CI 在 ubuntu 和 macOS 上全部通过）
- **复盘报告**：无（人工改动，来自实测）

---

## v0.9.0（2026-11-26）

新增 `/hq-blueprint`（一键把各阶段串起来）和 `/hq-launch`（上线检查），以及 `stage-status.py`。`docs/design-stages.md` 第 8 节的落地顺序全部完成。

### 新增 `/hq-blueprint` 一键蓝图和 `stage-status.py`
- **改动**：新增 `skills/hq-blueprint/SKILL.md`（`disable-model-invocation: true`）：按 research → prd → design 与 arch 并行 → plan（可选 build）的顺序串联各阶段，每个阶段按它自己的技能执行；参数 `--until`、`--from`、`--skip`、`--no-pause`、`--ask`，各阶段参数原样转交；阶段关卡（不过关就停）；只在需求阶段之后为未决 `D-xx` 暂停一次；产出 `blueprint.md` 项目索引。新增 `scripts/stage-status.py`（只读）：列出每个阶段产物是否齐全、版本、是否过期（`based_on` 引用的上游版本已更新）、调用各检查脚本得到的错误数，给出 `ok / missing / partial / needs_work / stale`。测试 `tests/test_stage_status.py`（用其他测试的样例搭一个完整项目，再逐项改坏）。`hq/SKILL.md` 常驻模式推荐下一批时，有文档目录就先看 `stage-status.py`，一个版本做完时推荐 `/hq-launch`。
- **原因/假设**：用户希望把一人公司的工作流尽量一键自动执行，遇到决策先按最优策略自己定，实在定不了再问。逐个敲阶段命令既繁琐又容易漏掉“上游改了、下游没跟”；`stage-status.py` 让串联只跑需要跑的。单个阶段里“按推荐先写、最后一次问”没问题，但在串联里需求阶段的大决定被三个下游阶段依赖，猜错的返工超过 hq 停止条件 3 的门槛，所以只在这里停一次。
- **验收指标**：一次 `/hq-blueprint` 运行结束时 `stage-status.py` 的 `todo` 为空（停在关卡的除外，且汇报写明原因）；`autonomy_stops` ≤ 2（输入为空时的提问和需求后的决策暂停）；设计和架构的并行让这两步的总用时比串行少 30% 以上（至少 3 次运行后统计）。
- **状态**：待验证（`stage-status.py` 自测通过；PR #29 的 CI 在 ubuntu 和 macOS 上全部通过；尚未在真实项目上运行）
- **复盘报告**：无（人工改动）

### 新增 `/hq-launch` 上线检查
- **改动**：新增 `skills/hq-launch/SKILL.md`（`disable-model-invocation: true`）、`template-checklist.md`（八个方面 46 项标准清单 L-01–L-46、结论规则、阻塞问题和需要你确认两节）、`template-runbook.md`（运维手册）。参数 `--release`、`--market`、`--check-only`、`--panel`。任务图：侦察 → 产品与质量、安全、隐私与合规、运维、运营商务发布五路并行（能用命令验证的实际跑：全量测试、构建、依赖漏洞审计、密钥扫描）→ 起草缺少的材料 → 汇总 → 独立抽查 5 条“通过”。结论规则：有不通过的 blocker → 暂不上线；有不通过的 major 或待人工确认的 blocker → 有条件上线；否则可以上线。法律文本只有草稿时记“待人工确认 + blocker”。不部署、不发布、不付费、不注册外部账号。`doc-check.py` 新增 `launch` 子命令：46 项齐全、结果和严重程度取值、“通过”有证据、“不适用”有原因、结论不比规则更乐观、阻塞问题和待确认项都已列出。新增角色卡 `roles/legal.md`（只做风险提示和草稿，不构成法律意见）、`roles/growth.md`、`roles/business.md`。新增 Gemini 命令 `commands/hq-blueprint.toml`、`commands/hq-launch.toml`；`install.sh` 技能列表加入两者；`stages/common.md` 产物目录、第 8、9 节同步；README 中英文、宿主文档、`adapters/gemini/README.md`、`docs/design-stages.md` 同步。
- **原因/假设**：用户希望插件覆盖从想法到上线的全部工作流，包括安全、运维、法务、商务、运营。上线前的问题往往不在代码里（备案、法律文本、备份、告警、收费流程），一份带证据要求和固定结论规则的清单能防止“看起来都好”的乐观判断；只有用户能看的项明确交给用户确认。
- **验收指标**：首次交付时 `doc-check.py launch` 错误数 = 0；抽查的 5 条“通过”全部属实；结论为“可以上线”的版本上线后一周内发现的、清单本应覆盖的问题 = 0（至少 3 次上线后统计）。
- **状态**：待验证（`doc-check.py launch` 自测通过；PR #29 的 CI 在 ubuntu 和 macOS 上全部通过；尚未在真实项目上运行）
- **复盘报告**：无（人工改动）

---

## v0.8.0（2026-11-26）

新增 `/hq-design`（设计规范和高保真可点击原型）和 `/hq-arch`（架构设计、详细设计和决策记录）两个阶段技能，以及配套的检查脚本。

### 新增 `/hq-design` 设计阶段
- **改动**：新增 `skills/hq-design/SKILL.md`（`disable-model-invocation: true`）、`template-design-system.md`、`template-screens.md`、`prototype-schema.md`（`hq-prototype/1`），以及原型起步套件 `prototype-starter/`：纯 HTML/CSS/JS、离线可开；`assets/tokens.css`（默认“简洁易懂、现代好看”的设计变量，含深色模式）、`assets/base.css`（通用组件和五种状态样式）、`assets/app.js`（模拟登录和演示账号、本地模拟数据、模拟接口延迟、`?state=` 强制状态、原型工具条）、`manifest.js`（页面、账号、流程的单一清单）、登录和首页两个示例页、页面模板、原型目录页。参数 `--platform`、`--explore N`、`--brand`、`--scope`、`--figma`。任务图：侦察 → 页面与流程 → 风格（可并行探索 N 个方向）→ 模拟数据 → 页面按流程分组并行 → 静态检查和自动走查 → 视觉走查 → 产品、开发、测试评审。设计规则写明了默认风格和要避免的“AI 风格”。新增 `scripts/prototype-check.py`（静态检查：清单格式、状态区块齐全、本地链接、从入口可达、流程引用的页面和 testid、外部资源、写死颜色、带 `--prd` 时的需求覆盖）和 `scripts/prototype-walk.mjs`（Playwright：逐页逐状态截图、记录控制台报错、执行流程；没有 Playwright 时退出码 3）。测试 `tests/test_prototype.py`（走查部分在没有 Node 或 Playwright 的环境自动跳过）。
- **原因/假设**：用户要求原型按上线标准把所有页面串起来，有一比一的完整交互流程、模拟账号和模拟数据，覆盖尽量多的场景，风格默认简洁易懂又时尚美观，交付前由相关专家评审且轮次可控。起步套件让并行写页面的子会话共用同一套登录、数据、状态和变量，保证一致；“状态区块 + 清单 + testid”让完整性可以用脚本验证，而不是靠自述。
- **验收指标**：首次交付时 `prototype-check.py` 错误数 = 0、`prototype-walk.mjs` 全部通过；评审中“流程走不通”“缺状态”类 blocker = 0；用户事后指出的缺页或走不通的流程 ≤ 1 处/次（至少 3 次运行后统计）。
- **状态**：待验证（自测通过；PR #27 的 CI 在 ubuntu 和 macOS 上全部通过：起步套件静态检查和 Playwright 走查都通过，手机和桌面截图人工看过；尚未在真实项目上运行）
- **复盘报告**：无（人工改动）

### 新增 `/hq-arch` 架构阶段
- **改动**：新增 `skills/hq-arch/SKILL.md`（`disable-model-invocation: true`）、`template-architecture.md`（12 章，含上下文、容器、数据、时序、部署图和需求映射）、`template-detailed.md`、`template-adr.md`、`diagram-style.md`（一张图一层、节点不超过 15 个、子图画边界、连线写标签、统一 `classDef` 配色，附示例）。参数 `--stack`、`--only arch|detailed`。任务图：侦察 → 关键选择并行调研 → 架构设计（T4）→ 详细设计（按模块并行）→ 检查 → 开发、安全、测试评审（有部署或成本约束时加运维）。`doc-check.py` 新增 `arch` 子命令：章节、第 2/3/5/6/7 章的图及类型、空图、节点数、配色、连线标签、模块字段、需求映射和 `--prd` 覆盖（P0 和非功能需求必须落到模块）、ADR 格式（标题、状态、背景、至少两个选项、决定、后果）、`--detailed` 覆盖每个模块。新增角色卡 `roles/ops.md`。`/hq-plan` 的输入表加一条：按模块写 `owns`，风险与待验证项排成先行调研任务，界面任务引用 `P-xx`、`FL-xx`。新增 Gemini 命令 `commands/hq-arch.toml`、`commands/hq-design.toml`；`install.sh` 技能列表加入两者；`stages/common.md` 的产物目录和第 9 节同步；README 中英文、`hosts/claude-code.md`、`hosts/gemini.md`、`adapters/gemini/README.md`、`docs/design-stages.md` 同步。
- **原因/假设**：用户要求根据需求文档和设计稿做架构设计和详细设计，架构图要简洁清晰、美观，让人一眼看懂全景和模块关联。画图规范把“好看、清楚”变成可检查的规则；需求映射保证没有需求落空；默认选一个人维护得了的方案，避免过度设计。
- **验收指标**：首次交付时 `doc-check.py arch`（带 `--detailed`、`--prd`）错误数 = 0；评审中架构图可读性类意见 ≤ 1 条/次；后续 `/hq --backlog` 执行中因架构缺项导致的升档或返工 ≤ 10%（至少 3 次运行后统计）。
- **状态**：待验证（自测通过；PR #27 的 CI 在 ubuntu 和 macOS 上全部通过；画图规范里的示例通过同一套检查；Mermaid 渲染未在本环境实测；尚未在真实项目上运行）
- **复盘报告**：无（人工改动）

---

## v0.7.0（2026-11-26）

新增 `/hq-research`（竞品调研）和 `/hq-prd`（需求文档）两个阶段技能，以及检查这两类文档的 `doc-check.py`。

### 新增 `/hq-research` 竞品调研阶段
- **改动**：新增 `skills/hq-research/SKILL.md`（`disable-model-invocation: true`）和 `template.md`（报告格式：元数据、结论摘要、调研范围、竞品概览、竞品详情 C-xx、对比矩阵、定价对比、用户痛点、机会点、对需求的建议、来源表）。参数 `--n`（默认 10，最多 20）、`--deep`（默认 3，最多 5）、`--market`、`--offline`。任务图：范围与候选 → 深挖每家一个任务并行、简析每任务 4–5 家并行 → 综合 → 机械检查 → 研究员事实核查（抽查 5 条）和产品评审。不能联网又没有 `--offline` 时停下说明，不凭模型记忆冒充调研。新增角色卡 `roles/researcher.md`。`stages/common.md` 新增第 7 节“联网与来源”（来源编号、推断标注、数字口径、只用公开信息），编号表加 `C-`、`S`、`D-`。新增 Gemini 命令 `commands/hq-research.toml`。
- **原因/假设**：用户要求按需求文档、产品描述或设计稿调研默认 10 家竞品，数量可指定，项目为空时提示输入。竞品调研最大的风险是编造，所以每条事实都要有来源、来源数按深度设下限、由研究员抽查。假设：深挖和简析并行后，10 家的调研总用时接近单家深挖的用时加综合。
- **验收指标**：首次交付时 `doc-check.py research` 错误数 = 0；研究员抽查的结论与来源一致率 ≥ 90%；用户事后指出的事实错误 ≤ 1 条/份（至少 3 份报告后统计）。
- **状态**：待验证（自测通过；PR #25 的 CI 在 ubuntu 和 macOS 上全部通过；尚未在真实项目上运行）
- **复盘报告**：无（人工改动）

### 新增 `/hq-prd` 需求阶段
- **改动**：新增 `skills/hq-prd/SKILL.md`（`disable-model-invocation: true`）和 `template.md`（12 章：概述、范围、用户旅程、功能需求 F-xxx、非功能需求 NFR-xxx、商业化、数据与埋点、上线必需项核对 24 项、风险、假设与待确认、需求索引、变更记录）。参数 `--from`、`--scope`、`--no-research`、`--ask`。没有调研报告时先做 5 家竞品速览；已有非模板格式的需求文档时原文件不动、另写一份；已有代码时已实现的功能也写成需求。任务图的关键是“骨架与关键决策”一步，主会话复核后才派功能详写，功能多时按模块并行。`/hq-plan` 的输入表加一条：直接读需求文档的“需求索引”。新增 Gemini 命令 `commands/hq-prd.toml`。
- **原因/假设**：用户要求按上线标准，结合想法、产品描述、设计稿或竞品截图产出完整需求文档，兼顾竞品、用户体验和商业化，交付前由相关岗位评审、轮次可控。上线必需项核对表防止漏掉注册登录、找回密码、注销账号、隐私政策这类基础功能；需求索引让 `/hq-plan` 不必再整理需求。
- **验收指标**：首次交付时 `doc-check.py prd` 错误数 = 0；评审发现的 blocker 中位数 ≤ 2；后续 `/hq-plan` 运行中因需求文档缺项而记的假设 ≤ 3 条/次（至少 3 次运行后统计）。
- **状态**：待验证（自测通过；PR #25 的 CI 在 ubuntu 和 macOS 上全部通过；尚未在真实项目上运行）
- **复盘报告**：无（人工改动）

### `doc-check.py`；改不回来的决定不再阻塞写作
- **改动**：新增 `skills/hq/scripts/doc-check.py prd|research`（只读）：需求文档检查元数据、必需章节、每个功能的优先级、用户故事、验收标准、五种界面状态、模板占位符、非功能类别、需求索引与正文一致、上线必需项每行有结论、有未决 `D-xx` 时不能 approved；调研报告检查元数据、必需章节、竞品类型和深度、每家竞品的来源数（深挖 ≥ 5、简析 ≥ 2）、引用都在来源表里、来源有 http(s) 链接和访问日期、竞品概览与详情一致、离线说明。测试 `tests/test_doc_check.py`（含模板与脚本的上线必需项清单一致性）。`stages/common.md` 第 6 节改为：改不回来的决定由用户拍板，但按推荐先写、记 `D-xx`、阶段结束时一次问（`--ask` 时先问）；真正的动作（付费、注册、对外发布）仍按停止条件。`install.sh` 技能列表加入 `hq-prd`、`hq-research`；README 中英文、`hosts/claude-code.md`、`hosts/gemini.md`、`adapters/gemini/README.md`、`docs/design-stages.md` 同步。
- **原因/假设**：用户希望尽量自动化，只在实在决定不了时找人。文档能改回，因此等用户回答再写只会拖慢进度；把格式问题交给脚本，评审者只看内容。
- **验收指标**：阶段运行的 `autonomy_stops` 中位数 ≤ 1（只计输入为空时的那一次提问）；评审意见里属于格式问题（缺字段、编号不一致）的比例 ≤ 10%。
- **状态**：待验证（自测通过；PR #25 的 CI 在 ubuntu 和 macOS 上全部通过）
- **复盘报告**：无（人工改动）

---

## v0.6.0（2026-11-26）

新增阶段技能的共用底座和第一个阶段技能 `/hq-plan`：把需求拆成版本计划和任务清单（带预估档位），评审后由 `/hq --backlog` 直接执行。整体设计见 `docs/design-stages.md`。

### 阶段技能共用底座：角色卡、通用规则、计划清单格式与检查脚本
- **改动**：新增 `docs/design-stages.md`（阶段技能的定位、命令命名、共用机制、自动调用的风险与对策、落地顺序）；`skills/hq/references/roles/` 6 张角色卡（pm、designer、architect、engineer、qa、security）和索引；`skills/hq/references/stages/common.md`（产物目录与元数据、编号与追溯、新建/补全/只评审三种模式、评审协议、决策优先级与找人条件、run 记录的阶段字段）；`skills/hq/references/backlog-schema.md`（`hq-backlog/1`）；`skills/hq/scripts/backlog-check.py`（只读检查：编号、依赖与环、版本顺序、档位与分数线、P0/P1 覆盖、并行任务的文件归属重叠、需求文档里遗漏的编号）及 `tests/test_backlog_check.py`。角色做成写进说明的角色卡，不放插件根目录 `agents/`。
- **原因/假设**：用户希望把一人公司从想法到上线的工作流放进插件，并由多岗位评审。角色和档位分开（角色决定看什么，档位决定花多少算力），所有宿主都能用；评审有轮次上限和严重程度分级，保证能收尾；改不回来的决定才找人。假设：共用规则让后续每个阶段技能只需写任务图和完成标准。
- **验收指标**：`/hq-plan` 产出的清单首次交付时 `backlog-check.py` 错误数 = 0；阶段运行的 `review_rounds` 全部 ≤ 3、≥ 80% 的运行 ≤ 2；`review_findings.unresolved` 中位数 ≤ 2（至少 5 次阶段运行后统计）。
- **状态**：待验证（自测通过；PR #23 的 CI 在 ubuntu 和 macOS 上全部通过；尚未在真实项目上运行）
- **复盘报告**：无（人工改动）

### 新增 `/hq-plan` 计划阶段
- **改动**：新增 `skills/hq-plan/SKILL.md`（`disable-model-invocation: true`，只能手动输入命令调用）：输入判断（有需求文档 / 只有想法 / 什么都没有 / 全新项目 / 已有代码）、任务图模板（侦察、起草、机械检查、评审、修改、复核）、起草规则（纵向切版本、任务粒度 15–120 分钟、测试跟着代码任务走、每版本一个 e2e 发布检查、按 5 维打分预估档位）、10 条完成标准、交付与汇报。新增 Gemini 命令 `commands/hq-plan.toml`；`install.sh` 的技能列表改为 `SKILLS` 变量并加入 `hq-plan`，`--update` 时把新版本新增的技能补装到已更新 `hq` 的目录（`tests/test_install.sh` 17b）；README 中英文、`hosts/claude-code.md`、`hosts/gemini.md`、`adapters/gemini/README.md` 同步。
- **原因/假设**：用户要求按需求、设计、技术文档拆分版本计划和任务，并评估每个任务的难度，方便执行时分配模型和思考深度。它离现有引擎最近，产出可以用脚本检查，先做它。阶段技能很重，不能因为用户随口提到“计划”就自动触发。
- **验收指标**：按计划执行的任务里，`plan_tier` 与实际 `tier` 一致的比例 ≥ 70%（至少 10 个任务）；用户手动调整计划（`user_manual_adjust`）的任务 ≤ 20%；没有阶段技能被自动调用的报告。
- **状态**：待验证（自测通过；PR #23 的 CI 在 ubuntu 和 macOS 上全部通过；尚未在真实项目上运行）
- **复盘报告**：无（人工改动）

### `/hq --backlog` 按计划执行，记录计划预估档位
- **改动**：`skills/hq/SKILL.md` 新增“按计划执行”一节（进入方式、先跑 `backlog-check.py`、清单任务作为第 2 步的任务图、第 3 步按当前代码重新打分并记 `plan_tier`、合并后回写清单状态）；常驻模式“推荐下一批”加入计划清单来源，并可以推荐阶段命令但不自动运行；第 9 步 task 字段加 `plan_tier`。`metrics-schema.md` 加 `plan_tier` 和阶段可选字段；`metrics.py` 新增“3e 计划预估档位 vs 实际”和对应信号（n ≥ 5 且偏低或偏高超过 30%），脱敏导出保留 `plan_tier`；`hq-retro/SKILL.md` 复盘清单第 11 项：据此改 `/hq-plan` 的打分说明，不改 `calibration.md`。
- **原因/假设**：计划阶段的预估只是起点，执行时代码状态可能已经变化；记下预估和实际的差别，`/hq-retro` 就能校准计划阶段的打分，形成“计划 → 执行 → 复盘”闭环。
- **验收指标**：按计划执行的任务一次通过率不低于非计划任务（每组至少 5 个）；“3e”一节的预估偏低比例在两次复盘之间下降或保持 ≤ 30%。
- **状态**：待验证（`tests/test_metrics.py` 新增用例通过；PR #23 的 CI 在 ubuntu 和 macOS 上全部通过）
- **复盘报告**：无（人工改动）

---

## v0.5.4（2026-11-25）

选档只看任务难度：用户要求尽量多开并发时不降模型和思考深度，只有明确授权才降。

### 档位只看任务难度，不因多开并发而降档
- **改动**：`calibration.md` 新增规则 11：模型和思考深度只按 5 维打分和规则 1–10 选，与并发数、任务总数无关；“尽量多开”、槽位或预算紧张、接近上限、限流都只能调并发、排队、打包和批次，不准降档，规则 9 的“拿不准往上选”照常执行；唯一例外是用户原话明确授权“为多开可以用低档”，此时按用户说的范围降（没说就最多一档），风险 2、T4、决定拆分的调研和所有审核默认不降，notes 记 `downgrade:user_allowed(-N)`，失败后升回按难度选的档位。规则 9 的“不上调的情况”去掉限流，改为限流时先降并发、不撤销上调。`SKILL.md` 新增铁律 8，第 3 步和第 5 步各补一条；`hq-retro/SKILL.md` 禁止以“多开”为理由建议降档；`hosts/codex.md`、`dsh.md`、`deepseek.md` 的限流说法、`PROMPT.md`、README 中英文同步；校准表版本升到 0.5.4。
- **原因/假设**：用户要求（2026-11-25）：用户说“尽量多开并发”时，不能因此降低子会话的模型和思考深度；档位必须严格按难度匹配，不确定时还要上调，除非用户明确说为了多开可以用低一点的。原规则没写并发和档位的关系，限流时还会撤销上调，多开场景下容易被理解成“降档换并发”。假设：分开处理后，多开场景的一次通过率与普通运行持平，返工不上升，代价只是部分任务排队。
- **验收指标**：没有 `downgrade:user_allowed` 标记的任务里，档位低于其打分对应档位（含规则 9 上调）的记录 = 0；`max_concurrency` ≥ 4 的运行，一次通过率比其他运行低不超过 5 个百分点（每组至少 5 个运行）；带 `rate_limited` 的任务没有同时出现档位下调。
- **状态**：待验证（自测全部通过；PR #20 的 CI 在 ubuntu 和 macOS 上全部通过）
- **复盘报告**：无（人工改动）

---

## v0.5.3（2026-11-25）

加许可证（Apache-2.0 加 Commons Clause）和仓库配套文件，不改任何技能行为。

### 增加许可证、贡献与安全文档、CI
- **改动**：新增 `LICENSE`（Apache-2.0 官方全文，前面加 Commons Clause v1.0 条件）；`plugin.json`、`marketplace.json` 加 `author`、`homepage`、`repository`、`license`（`SEE LICENSE IN LICENSE`，组合协议没有单一 SPDX 标识）；两个 `SKILL.md` 的 frontmatter 加 `license`（只装技能目录时也能看到许可）；中英文 README 末尾加“许可与商用”一节；新增 `CONTRIBUTING.md`（含贡献授权条款）、`SECURITY.md`、PR 模板、问题报告模板、`.github/workflows/test.yml`（ubuntu 和 macOS 上跑全部自测）。
- **原因/假设**：任何人可以免费使用（含公司内部和商业项目），但不得把本项目打包出售或收费提供托管、咨询、支持；作者自己可以出售和收费支持。贡献条款让作者能把外部贡献放进自己出售的版本。假设：这些文件不影响技能行为，也不影响安装和测试。
- **验收指标**：`tests/` 全部通过（与改动前一致）；CI 在 ubuntu 和 macOS 上首次运行通过。
- **状态**：待验证（macOS 本机自测全部通过；PR #17 的 CI 在 ubuntu 和 macOS 上全部通过）
- **复盘报告**：无（人工改动）

---

## v0.5.2（2026-11-25）

`resources.sh` 读不到读数时报 UNKNOWN，不再误报 RED；写明 Codex 作主宿主时的沙箱限制（实测 assist 熔断的结论）。

### resources.sh 读不到读数时报 UNKNOWN；写明 Codex 作主宿主时的沙箱限制
- **改动**：`scripts/resources.sh` 每项读数读不到（`sysctl`、`vm_stat`、`/proc` 被拒或没有）时不再当成 0：输出里记为 `null`，新增 `unreadable` 数组和 `reason` 里的“无法读取:…”；已读到的读数没到 RED 时 `level` 为 `UNKNOWN`、`new_local_slots` 最多 1，读到的读数显示 RED 时仍为 RED；新增测试注入 `HQ_FAKE_UNREADABLE`。`tests/test_resources.sh` 的 `over()` 不再用 `local -n`（macOS 自带 bash 3.2 不支持，原先 4 项失败），新增 7 项 UNKNOWN 用例。`SKILL.md` 第 5 步补 `UNKNOWN` 的处理（按 YELLOW），第 1 步辅助预检补“能否建 worktree”；`calibration.md` 规则 10 的关键路径条件加 `UNKNOWN`；`hosts/codex.md` §5 第 9 条改为实测结论；README 中英文同步。
- **原因/假设**：2026-11-25 在 Codex（0.172.0，`codex exec --approve-for-me`）里实测 assist 熔断：沙箱禁止 `sysctl`，旧脚本把读不到当成 0，报 `RED`/0 槽位，会挡住所有本地派发；同时沙箱禁止写 `.git`，W 通道建不了 worktree、主宿主也提交不了。熔断本身按规则 10 正常工作（`same_as_host` 跳过、缺 `env_file` 和建不了 worktree 都记为不可用、剩余任务全部由 Codex 自己做、`autonomy_stops: 0`）。假设：区分“读不到”和“资源紧张”后，沙箱宿主不会再被误判为 RED。
- **验收指标**：沙箱宿主（Codex 等）的运行里，因 `resources.sh` 误报 RED 而 `throttle_events` > 0 的次数 = 0；`level: UNKNOWN` 的运行里，因资源不足被 stop_worker 的任务 = 0。
- **状态**：待验证（`test_resources.sh` 26/26；在 `codex sandbox` 里实跑：旧脚本 RED/0、新脚本 UNKNOWN/1）
- **复盘报告**：无（人工改动）

## v0.5.1（2026-11-25）

Codex 辅助执行者实机核实与 macOS 修复；选档“拿不准往上选”扩展到所有宿主；辅助执行者停用（熔断）规则，主宿主不再假定是 Claude。

### 辅助执行者：不可用或屡次失败就停用，主宿主不再假定是 Claude
- **改动**：`calibration.md` 规则 10 写明“主宿主”是运行本插件的宿主和模型（不一定是 Claude），profile 与主宿主相同（如 Codex 宿主上的 `codex`）时跳过；新增“停用（熔断）”：不可用（预检不过、worker 起不来、认证失败、限流、额度用完）立即停用，连续失败 2 次或累计失败达到 `assist.max_failures`（默认 2）停用，并定义了“失败”；全部停用时本次剩余任务全部由主宿主执行、按主宿主映射重新选档、不停下问用户，台账头部记 `assist: off（熔断：…）`；常驻模式停用持续到会话结束。`SKILL.md` 辅助执行者一节和第 1 步预检、`playbook-template.md` 新增 `max_failures`、`metrics-schema.md` run 记录新增可选字段 `assist_disabled`、`hosts/codex.md` §5 新增第 9 条、`hosts/kimi.md`、README 中英文、`PROMPT.md` 同步。
- **原因/假设**：用户要求（2026-11-25）：辅助模型不可用、频繁或连续失败时，放弃辅助、全部由主模型执行；插件也会运行在 Codex 等宿主上，不能假定主模型是 Claude。原规则只写“累计失败 2 次跳过”，没写全部停用后怎么办，文案里多处写“主宿主（如 Claude）”，在 Codex 宿主上还可能把 `codex` 当成自己的辅助。假设：熔断后不再反复派给坏掉的辅助，回收浪费下降，总用时不因辅助拖长。
- **验收指标**：开启 `assist` 的运行里，同一 profile 在被停用后仍被派发的任务数 = 0；单次运行里辅助失败任务数 ≤ `max_failures`（不可用导致的除外）；非 Claude Code 宿主上 `assist_skip:*:same_as_host` 之外，没有把主宿主自己的 CLI 当辅助派发的记录。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### 拿不准难度时所有宿主都往上选一步
- **改动**：`calibration.md` 规则 9 从“只对低成本宿主上调一档”改为所有宿主都上调一步：`cost_weight: low` 上调一整档；`high`（如 Claude Code）默认只把思考深度上调一级、模型不变，模糊度 ≥1 或风险 2 时上调一整档；上限一步，不动用 `xhigh`/`max`；notes 标记改为 `bias:+1(tier)` / `bias:+1(effort)`（旧 `bias:+1(cost_low)` 等同 `tier`）。规则 1 补一句指向规则 9。`SKILL.md` 第 3 步、`hosts/codex.md`、`dsh.md`、`deepseek.md`、`generic.md`、`playbook-template.md` 的 `cost_weight` 注释、README 中英文、PROMPT.md 同步。
- **原因/假设**：用户偏好（2026-11-25）：难度评估不太确定时，尽量提高一档模型或思考深度。原规则在 Claude Code 上拿不准仍选最低档，失败重来的代价（重新熟悉项目、交接丢上下文）通常大于差价。假设：高成本宿主只上调思考深度就能拿到大部分收益，花费增幅小于换模型。
- **验收指标**：带 `bias:+1(*)` 标记的任务，一次通过率比同档未上调的任务高至少 10 个百分点（每组至少 5 个任务）；`high` 宿主上调后每任务平均 cost_usd 增幅不超过 30%；返工率不上升。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### Codex 辅助执行者实机核实；修 macOS 上 W 通道起不来、Codex worker 提交不了
- **改动**：`scripts/cli-worker.sh` 启动 runner 时，没有 `setsid`（macOS）就改用 `python3` 的 `os.setsid()` + exec；runner 新增第 5 个参数，后端设 `BE_COMMIT=1` 时，CLI 退出码为 0 且 worktree 有改动，就在沙箱外 `git add -A && git commit` 到 `hq/<id>`（失败只写 `log`）。`scripts/backends/codex.sh` 在 `workspace-write` 下设 `BE_COMMIT=1` 并写 notes，文件头改为“已实机核实”。`tests/fixtures/fake-cli/codex` 按实测事件格式补 `thread.started`、`error` 警告项、`agent_message`、`cache_write_input_tokens`，新增 `FAKE_WRITE`；`tests/test_cli_worker.sh` 新增代提交 5 项用例；`tests/test_install.sh` 的 `wc -l` 去掉 BSD 前导空格。`references/hosts/codex.md` §5 第 1、3、7 条、`references/runtimes.md` W 节 codex 行的核实状态同步更新。
- **原因/假设**：2026-11-25 在 macOS 26.6.2 上用 codex-cli 0.172.0（模型 gpt-6.2-sol）实跑：① macOS 没有 `setsid`，`cli-worker.sh start` 后 runner 根本没起来，状态一直是 `unknown`（`test_cli_worker.sh` 27 项失败）；② Codex `workspace-write` 沙箱把 `.git` 当受保护路径，worktree 里 `git add` 建不了 `index.lock`，worker 无法提交，`--add-dir` 主仓库 `.git` 也无效。`-m`、`-c model_reasoning_effort=low|medium`、`-s read-only|workspace-write`、`--json`、`-` 都被接受（会话记录 `turn_context` 显示生效），usage 字段与 `be_usage` 一致，无需改。假设：代提交后，Codex 辅助任务在 macOS 上能按 `hq/<id>` 分支交付，主宿主照常审核。
- **验收指标**：开启 `assist: [codex]` 的运行里，codex 辅助任务因“分支上没有提交”而回收的次数 = 0；W 通道在 macOS 上 `state: unknown` 的 worker 数 = 0。
- **状态**：待验证（三套自测通过；smoke1c / smoke2 / smoke3 与 3 任务端到端（assist: codex，metrics 出现 3d）已实跑；`danger-full-access` 只在 `--help` 里核对，未实跑）
- **复盘报告**：无（人工改动）

## v0.5.0（2026-11-25）

### 辅助执行者：主宿主主攻难点，Codex / Kimi 承接中低难度
- **改动**：`calibration.md` 新增规则 10“分工路由”；`SKILL.md` 新增“辅助执行者”一节，第 1、3、4、8、9 步和授权配置、台账头部相应补充，支持 `/hq --assist <名单> [--assist-max T0|T1|T2]` 和 PLAYBOOK `assist`；`scripts/cli-worker.sh` 新增 `--env-file`（只注入 worker 进程，文件须 600，值不进 cmd/notes/输出）和 `--label`（写进 status/usage）；新建 `references/hosts/kimi.md`；`metrics-schema.md` task 新增可选字段 `assist`；`metrics.py` 新增“3d 辅助执行者 vs 主宿主”分组，脱敏导出保留 `assist`；`hq-retro` 复盘清单新增第 10 项；README 中英文、PROMPT.md 同步。
- **原因/假设**：用户希望大目标里难的、重要的任务由 Claude 自己做，其余交给 Codex、Kimi 等更便宜的模型并由 Claude 审核，以节省 Claude 额度、加快交付且不降质量。原来的 `worker_clis` 只是“允许用”，选档不会主动分流，也接不了 Kimi。假设：只把需求明确、低风险、易验证的 T0–T2 交出去，审核不降档、失败即收回，质量门槛不变，主宿主 tokens 明显下降。
- **验收指标**：开启 `assist` 的运行里（每组至少 5 个任务）：辅助各档一次通过率与主宿主同档相差不超过 20 个百分点；回收率（辅助任务的交接率）≤ 30%；返工率、合并通过率不劣于未开启时；主宿主侧每任务平均 tokens 下降。
- **状态**：待验证（`cli-worker.sh` 新参数和 metrics 分组已有自测；Kimi 接口、Codex 实际调用未实机运行）
- **复盘报告**：无（人工改动）

### 随 0.5.0 发布的此前未发布改动

补充 B 通道（云端子会话）通信能力的实测结论。只改文档。

### 子会话汇报在 auto 模式下不可用，补降级写法
- **改动**：`skills/hq/references/hosts/claude-code.md` §2 `message_worker` 行补主会话向子会话发消息的实测行为和 `priority` 三档，§5 新增“auto 模式下子会话主动汇报不可用”及巡检识别方法；`runtimes.md` B 通道补“回报可能发不出去”；`brief-template.md` 补“回报发不出去时不要停下，以交付格式和分支为准”；`SKILL.md` 监控一节补“`blocked` 且 `need_input` 多半是在等批准”。
- **原因/假设**：2026-11-25 用 haiku 子会话实测（权限模式继承 auto）：子会话 `send_message` 发给主会话会卡在人工批准上，发给兄弟会话被分类器拒绝，仓库里的 allow 规则和 `extra_allowed_tools` 预批准都没有放行。原文档默认子会话会主动回报，无人值守时会让主会话一直等不到消息。假设：说明里同时要求写交付文件、巡检识别 `need_input`，能让这类卡住在一次巡检内被发现。
- **验收指标**：auto 模式的云端运行里，因子会话等批准而卡住、且主会话超过 2 个巡检间隔才发现的任务 = 0。
- **状态**：待验证
- **复盘报告**：无（人工改动）

---

## v0.4.8（2026-11-25）

用时比信号也排除时间数据矛盾的 run。

### actual/est 排除矛盾 run
- **改动**：`skills/hq/scripts/metrics.py` 先算效率表，再把标了“数据矛盾”的 run 的任务排除在 actual/est 用时比之外：按档位、按模型/深度、按宿主/通道的中位数和总体中位数都不再计入它们；分组新增 `ratio_excluded`，报告备注列写“用时比排除矛盾 run 的 N 条”。依赖用时比的“估时偏乐观”“可能存在降档空间”信号随之不受矛盾数据影响；一次通过率、升档率、成本等照常统计。`metrics-schema.md` 同步说明。`tests/test_metrics.py` 更新断言：fixtures 里 T2、sonnet/medium 的用时比只来自 r2，现在为空且不报“估时偏乐观”，T1 不受影响。
- **原因/假设**：v0.4.7 只让加速比信号跳过矛盾 run，档位和模型的用时比仍在用同一批不可信的 `actual_min`。测试数据里 T2 的“估时偏乐观”信号全部来自 r2，属于误报；真实数据把等审核、合并时间算进 `actual_min` 时，也会把估时偏差夸大，进而误导选档校准。
- **验收指标**：复盘中“估时偏乐观”“可能存在降档空间”信号所依据的任务里，来自矛盾 run 的 = 0；这两类信号给出后经复盘查证属实的比例 ≥ 80%。
- **状态**：待验证
- **复盘报告**：无（人工改动）

---

## v0.4.7（2026-11-25）

加速比口径：识别矛盾的时间数据，减少“加速比偏低”误报，写清 `actual_min` 怎么取。

### 加速比数据矛盾检测与信号收紧
- **改动**：`skills/hq/scripts/metrics.py` 效率表新增“加速比上限”（actual_min 之和 / critical_path_min）和“备注”列；加速比 > max_concurrency × 1.1、或某个任务的 actual_min > wall_min 时备注“数据矛盾”，该 run 不再产生加速比信号，改为提示“时间数据矛盾，先核对 actual_min 口径”；“加速比 < 1.3”信号只在加速比上限 ≥ 1.3（任务图本来允许并行）时给出，没记 critical_path_min 的 run 不判断。`metrics-schema.md` 写明 `actual_min` = 从派发到 worker 交付的墙钟时间、不含等审核和合并，并补充效率各列与矛盾判定；`runtimes.md` 的 worker_usage 加通用取法（W 取 `cli-worker.sh status` 的 `minutes`），`hosts/claude-code.md` 加 B 通道取法（`created_at` 到交付那一轮结束）。`tests/test_metrics.py` 更新 r2（矛盾）、r3（无关键路径不报）的断言，新增串行依赖链不报、可并行却串行执行要报、容差边界的测试。
- **原因/假设**：2026-11-25 云端复盘中，子代理发现测试数据 r2 加速比 3 而 max_concurrency 只有 1，怀疑公式有误。核实后公式正确（平均同时在跑的任务数），是数据自相矛盾：1 个并发下 3 个任务合计 90 分钟、单个任务 40 分钟，都超过整批 30 分钟。真实运行里如果 `actual_min` 把等审核、合并的时间算进去，会出现同样的虚高，而原报告不会提示。另外，原“加速比偏低”信号在串行依赖链上必然触发，是误报。
- **验收指标**：真实运行的复盘里，标“数据矛盾”的 run 占比在口径写清后的 5 次运行内降到 0；“加速比偏低”信号给出后，复盘确认属实（确有可以并行却没并行的任务）的比例 ≥ 80%。
- **状态**：待验证
- **复盘报告**：无（人工改动；起因见 2026-11-25 云端 hq-retro 验证）

---

## v0.4.6（2026-11-25）

运行记录可以保存进项目仓库，云端跨会话也能复盘；可以手动导出脱敏数据分享给插件作者。

### 运行记录保存进仓库
- **改动**：新增 `skills/hq/scripts/runs-persist.sh`：`save branch` 用 git 底层命令把 `.hq/runs/*.jsonl` 写进专用分支 `hq/runs` 的 `runs/` 下并推送（不碰工作区和当前分支；只追加；别的会话同时推送时重新拉取再试，最多 3 次；推不上退出码 3）；`save commit` 只把记录文件提交到当前分支；`fetch` 取回到 `.hq/runs-archive/`。`SKILL.md` 第 9 步删去“云端不需要保存”，按 PLAYBOOK 新项 `runs_persist: off|branch|commit` 保存，`branch` 推不上就降级为 `commit` 并改写 PLAYBOOK；云端没写这项时在第一次汇报里问一次。授权配置、`playbook-template.md` 加 `runs_persist`。`hq-retro` 第 1 步先 `fetch` 再把 `.hq/runs-archive` 一起汇总。新增 `tests/test_runs_persist.sh`（26 项）。README 中英文加“运行记录与数据分享”一节。
- **原因/假设**：云端容器回收后 `.hq/runs/` 丢失（2026-11-25 云端实测 `/hq-retro` 只看到本会话数据），主要在云端使用的项目永远凑不够复盘门槛。存进项目仓库后数据和代码在同一信任范围，不涉及第三方。
- **验收指标**：开了 `runs_persist: branch` 的云端项目，`/hq-retro` 的 run 数等于实际运行过的批次数（缺失 = 0）；`runs-persist.sh` 推送失败后降级为 `commit` 的次数单独记进 notes，比例不应超过 50%（超过说明云端默认应改为 `commit`）；保存步骤导致的 `autonomy_stops` 只有云端首次那一次。
- **状态**：待验证（本地用 bare 仓库测过并发、降级和取回；2026-11-25 云端会话实测 `save branch` 推送 `hq/runs` 成功、`fetch` 取回成功，但云端删不掉远程分支，测试分支需手动删除）
- **复盘报告**：无（人工改动）

### 手动导出脱敏数据
- **改动**：`metrics.py` 加 `--export-anon [--raw]`：先按白名单裁剪每条记录再汇总，只保留枚举、数字、布尔字段，删掉 `title`、`project`、`goal`、`notes`、`drift_note`、`tier_changes.reason` 和未知字段，`run_id` 哈希、`task_id` 换序号、时间只留日期、`verify_evidence` 只留有无；非法枚举和不合规的 model/effort 写 `other`。`hq-retro` 加 `/hq-retro --export`：完整显示导出内容并存到 `.hq/retro/export-<日期>.json`，由用户自己用新增的 `.github/ISSUE_TEMPLATE/retro-data.md` 开 issue，绝不自动上传；复盘报告末尾只提示一次（PLAYBOOK `share_hint`）。`metrics-schema.md` 写明白名单。`tests/test_metrics.py` 加 3 个测试（导出后指标不变、自由文本和未知字段不泄露、`--raw` 必须配 `--export-anon`）。
- **原因/假设**：插件作者只能看到自己的运行数据，选档校准缺少别的宿主、项目的样本。自动上传无处可传（其他用户没有仓库写权限，PR 和 issue 公开，自建服务要运维且会被云端代理拦），靠模型脱敏也不可靠；改为确定性白名单加用户主动分享，用户每次都能看到传出的完整内容。
- **验收指标**：收到的 retro-data issue 中，含任何自由文本或项目名的 = 0；`share_hint` 提示后用户反馈“被打扰”= 0；出现来自至少 2 个不同宿主的分享后，`calibration.md` 至少有 1 条改动的依据来自分享数据。
- **状态**：待验证
- **复盘报告**：无（人工改动）

---

## v0.4.5（2026-11-25）

新增常驻模式：同一个会话一批接一批地当总指挥，并支持接管已有会话。

### 常驻模式
- **改动**：`skills/hq/SKILL.md` 新增“常驻模式”一节（`/hq --stay`、“常驻司令部”进入，`/hq --stop`、“退出常驻”退出）：批次结束不退出、新目标开新一批（新 run_id，第 0 步照常判断）、提问不退出、上一批仍在跑时新批不能改其归属文件；接管已有会话时把聊天里的进度写进台账“接管背景”；台账头部加 `mode`、`skill_path`、`batch`，每回合发现记不清流程就重读 `skill_path`；每批任务表压成一行移到“历史批次”。description 加常驻触发词。`metrics-schema.md` run 记录加可选字段 `standing_seq`（读取方忽略未知字段，`metrics.py` 不需改）。`PROMPT.md` 加“常驻”一段。README 中英文加“常驻模式”一节，含不重开会话、靠读取 SKILL.md 接管的写法。版本号同步为 0.4.5。
- **原因/假设**：用户常在已积累大量上下文的会话里连续推进多批工作，开新会话要重新交代进度。常驻后不必换会话；状态写在台账里，压缩或换会话后也能接上。
- **验收指标**：带 `standing_seq` 的 run 中，第 2 批及以后的 run 质量门槛（漂移率、验证到位率、返工率）不差于非常驻 run；用户反馈“压缩后不再派子会话 / 忘了常驻”的次数 = 0；常驻 run 的 `autonomy_stops` 中因“接不上之前进度”而问用户的次数 = 0。
- **状态**：待验证（只做了文档改动和现有测试，未在真实会话里跑过多批）
- **复盘报告**：无（人工改动）

### 常驻模式：推荐下一批与完工声明
- **改动**：`SKILL.md` 常驻模式加“推荐下一批”：每批汇报后从台账（待办池、未派衍生任务、BLOCKED/FAILED、后续问题）、会话（接管背景未完成项、总目标未覆盖部分）和项目（路线图、待验证项、TODO/FIXME、open issue、失败测试）收集候选，只保留有来源的，最多 5 条并排序；回复“按推荐”开始，用户说过“按推荐自动继续”时直接开下一批。没有可执行候选且总目标已满足时明确声明“项目当前所有任务都已执行完毕，没有更多可执行任务了”，附检查过的来源。进入常驻时建“总目标”和“待办池”。内容多时派 T0/T1 只读调研，主会话不亲自读。`metrics-schema.md` run 加可选字段 `from_recommendation`、`recommended_next`。`PROMPT.md`、README 中英文、PROMPT.md 同步。
- **原因/假设**：用户不用每批自己想下一步；有证据的推荐减少遗漏，明确的完工声明避免空转或硬编任务。
- **补充（无目标进入）**：`/hq --stay` 不带目标时先探索项目（推荐来源之外补看 README/docs 定位、近 20 条提交、未合并分支、轻量测试和 lint、过期依赖或文档；大项目派 T1 只读调研），给出编号推荐，等用户回复编号、“按推荐”或自己的目标，进入时一律不自动开始；没找到待办时请用户给目标，不说完工。推荐统一编号，可按编号挑选。
- **验收指标**：无目标进入时，用户选用了至少一条推荐的比例 ≥ 50%；常驻 run 中 `from_recommendation=true` 的占比 ≥ 50%（推荐有用）；来自推荐的批次质量门槛不差于用户直接给目标的批次；完工声明后用户又指出“还有没做的既有任务”的次数 = 0。
- **状态**：待验证
- **复盘报告**：无（人工改动）

---

## v0.4.4（2026-11-25）

修复版本：macOS 自带 bash 3.2 下 `install.sh` 无法安装。

### 修复 bash 3.2 下 unbound variable
- **改动**：macOS 自带 bash 3.2 在 UTF-8 locale 下会把非 ASCII 字节当成变量名的一部分，`install.sh` 第 312 行的 `$s（供` 被读成变量 `s\xEF…`，在 `set -u` 下报 `unbound variable` 并退出（用户实测 `./install.sh --host auto` 复现）。把所有紧跟非 ASCII 字符的变量改成 `${var}`，共 14 处：`install.sh`（下载失败、未知宿主、安装计划、安装、完成提示）、`adapters/render.sh`（模板描述、占位符注释、`--check` 提示）、`skills/hq/scripts/backends/{cursor,gemini,opencode}.sh`（忽略 `--effort` 的提示）。生成的模板内容不变（`render.sh --check` 三种格式一致）。`tests/test_install.sh` 加第 33 项回归检查（用 perl 扫描所有 `.sh`，macOS grep 不支持 `-P`），增至 72 项。版本号在 install.sh、两个 Claude 清单、Gemini 清单和 README 的安装命令同步为 0.4.4。
- **原因/假设**：macOS 是主要用户平台之一，默认 bash 就是 3.2；修复后 macOS 上能一次装好，W 通道的 cursor、gemini、opencode 后端在带 `--effort` 时也不会中途退出。
- **验收指标**：`tests/test_install.sh` 全部通过；macOS 自带 bash 下 `./install.sh --host auto` 退出码 0；用户反馈“install.sh 报 unbound variable”的问题数 = 0。
- **状态**：待验证（只在 Linux 的 bash 5 上跑过测试，macOS bash 3.2 待实机确认）
- **复盘报告**：无（人工改动）

---

## v0.4.3（2026-11-25）

本版本让整个仓库可以作为 Gemini CLI 扩展安装，并把 Gemini CLI 升级为原生宿主。依据 GitHub google-gemini/gemini-cli 的官方文档（2026-11-24 的提交：`docs/extensions/reference.md`、`docs/core/subagents.md`、`docs/cli/skills.md`、`docs/cli/custom-commands.md`），**没有实机运行**；官方把子代理标为预览功能。

### Gemini 扩展
- **改动**：仓库根目录新增 `gemini-extension.json`（name `hq-orchestrator`，不设 `contextFileName`）和 `commands/hq.toml`、`commands/hq-retro.toml`（`/hq <目标>`、`/hq-retro`，提示模型用 `activate_skill` 激活对应技能，`{{args}}` 传目标）；扩展的技能直接用现有 `skills/`。扩展**不带**子代理：根目录 `agents/` 会被 Claude Code 插件当成自己的子代理加载，所以模板放在 `adapters/gemini/agents/` 由 install.sh 安装。`install.sh` 在 `--host gemini` 且已装扩展时提示重复（用户目录的技能优先于扩展）；卸载提示包含 Gemini 模板和扩展卸载命令。版本号在 install.sh、两个 Claude 清单和 Gemini 清单四处一致（有测试）。
- **原因/假设**：只用 Gemini CLI 的用户一条 `gemini extensions install` 就能装好，并有和 Claude Code 一致的 `/hq` 入口。
- **验收指标**：`tests/test_install.sh` 全部通过；用户反馈“扩展装不上 / `/hq` 激活不了技能”的问题数 = 0；Claude Code 插件里不出现 `commands/*.toml` 对应的命令。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### Gemini CLI 原生宿主
- **改动**：新增 `skills/hq/references/hosts/gemini.md`（子代理以同名工具 `hq-t0…t4` 调用、同步返回、不能续发消息；与主会话共用工作区，改代码任务先建 worktree；没有思考深度，只靠模型区分档位；用量填 null，W 通道可读；成本系数默认 low）。`adapters/render.sh` 新增 gemini 格式（`name`、`description`、`kind: local`、可选 `model`、`max_turns: 100`、`timeout_mins: 60`），生成 `adapters/gemini/agents/` 和 README；`agent-dirs.tsv` 加 `~/.gemini/agents`；`hosts.tsv` 中 gemini 改为 native。`SKILL.md` 加 gemini 识别，脚本查找路径加扩展目录；`runtimes.md`、`calibration.md`（Gemini 行、规则 9 成本系数）、`generic.md` 同步。`tests/test_install.sh` 增至 71 项。
- **原因/假设**：Gemini CLI 子代理可在定义文件里设 `model`，档位能逐任务生效，比降级模式快。
- **验收指标**：3c 按宿主/通道 → `gemini/A` 组有 ≥3 个任务时一次通过率 ≥ 70%；notes 含 `tier:not-applied` 的 gemini 任务占比 ≤ 20%；问题数里“子代理越界改主工作区” = 0。
- **状态**：待验证
- **复盘报告**：无（人工改动）

---

## v0.4.2（2026-11-25）

### W 通道后端化，新增 opencode、gemini、cursor
- **改动**：`skills/hq/scripts/cli-worker.sh` 拆成公共框架 + `scripts/backends/<cli>.sh`（`be_argv` 拼命令、`be_usage` 解析用量，接口见 `backends/README.md`）；codex、claude 行为不变。新增三个后端：opencode（`opencode run --model p/m#variant --format json`，简报走 stdin，`--effort` 追加为 variant，用量为 `step_finish` 的 input+output+reasoning+cache.write 逐步相加、cost 相加）、gemini（`gemini -m … --output-format stream-json --approval-mode … -p …`，简报走 stdin，用量取 `result.stats` 的 input_tokens−cached+output_tokens，不支持思考深度）、cursor（`cursor-agent -p --output-format stream-json --model … [--force] "<简报>"`，用量字段待核实）。后端可在建 worktree 前拒绝组合；映射有出入时写 `.hq/workers/<id>/notes` 并在 `start` 输出里返回。`--allow-dangerous` 闸门对所有 CLI 统一生效。`runtimes.md` W 节加各 CLI 映射表；`worker_clis` 可选值扩为五个，宿主自己的 CLI 不需授权；`generic.md` 让 Cursor、Gemini CLI 宿主经 W 用自己的 CLI 让档位生效；`opencode.md` 加 W 用法。假 CLI 加 opencode、gemini、cursor-agent；`tests/test_cli_worker.sh` 增至 53 项。
- **原因/假设**：Cursor、Gemini CLI 的原生子代理还不能按任务选模型，用它们自己的无界面命令做 worker 就能让档位生效；后端文件化后新增 CLI 只加一个文件。
- **依据**：opencode 来自 GitHub sst/opencode（2026-11-25）的 `run` 帮助夹具和 `run.rs`/`prompt.rs`；gemini 来自 google-gemini/gemini-cli 的 `docs/cli/headless.md`、`cli-reference.md` 和 `packages/core/src/output/types.ts`（2026-11-24）；cursor 来自官方参数页的检索摘要。**三者都未实机运行。**
- **验收指标**：`tests/test_cli_worker.sh` 全部通过；3c 按宿主/通道 → W 通道下 opencode/gemini/cursor 各组有 ≥3 个任务时一次通过率 ≥ 70%，`usage` 的 tokens 非 null 占比 ≥ 80%（cursor 除外，字段待核实）；问题数里“W worker 越界改主工作区” = 0。
- **状态**：待验证
- **复盘报告**：无（人工改动）

---

## v0.4.1（2026-11-25）

本版本把 OpenCode（V2）升级为原生宿主，并让子代理档位模板由一份档位表生成。OpenCode 部分**只读过官方文档源码（GitHub sst/opencode，2026-11-25），没有实机运行**。

### OpenCode 宿主适配
- **改动**：新增 `skills/hq/references/hosts/opencode.md`（5 节：`subagent` 工具按 `hq-t0…t4` 派发、后台运行并以 `<subagent>` 消息通知、带 `sessionID` 续发消息；stop_worker、worker_usage 待核实；子代理与主会话共用工作目录，改代码任务由主会话先建 `.hq/worktrees/<id>` 并在派发前后检查主工作区 `git status`；成本系数按 provider 判断）。`SKILL.md` 第 1 步加 opencode 识别（与 dsh 的 `subagent` 以参数区分）；`runtimes.md`、`calibration.md` 加 OpenCode 行；`generic.md` 移出 OpenCode；`hosts.tsv` 中 opencode 改为 native。
- **原因/假设**：OpenCode V2 的子代理可在 agent 文件里设 `model: provider/model#variant`，五档能逐任务生效，比降级模式快且省。
- **验收指标**：3c 按宿主/通道 → `opencode/A` 组有 ≥3 个任务时一次通过率 ≥ 70%；notes 含 `tier:not-applied` 的 opencode 任务占比 ≤ 20%；问题数里“子代理越界改主工作区”= 0。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### 子代理模板生成器与 `--with-agents`
- **改动**：新增 `adapters/tiers.tsv`（T0–T4 的思考深度、模型档次、适合任务）、`adapters/render.sh`（生成 codex TOML 和 OpenCode V2 Markdown，`--model-map` 填模型，`--check` 校验、`--all` 重新生成）、`adapters/agent-dirs.tsv`（模板安装目录）；`adapters/codex/agents/` 改为生成产物（内容只改了注释），新增 `adapters/opencode/agents/` 和 README。`install.sh` 新增 `--with-agents`（按所选宿主装模板）和 `--model-map`（只对一个宿主），保留 `--with-codex-agents`；卸载提示包含 OpenCode 模板目录。`tests/test_install.sh` 增至 64 项（生成结果与仓库一致、V2 格式、映射规则、非法映射、安装目录、多宿主、已存在不装一半、dry-run）。
- **原因/假设**：每加一个宿主就多 5 个手写模板，容易漂移；安装时直接填模型，避免用户手改占位符。
- **验收指标**：`tests/test_install.sh` 全部通过；用户反馈“模板模型未替换/格式错误”的问题数 = 0。
- **状态**：待验证
- **复盘报告**：无（人工改动）

---

## v0.4.0（2026-11-25）

本版本让 hq 能一键安装到更多代理工具（OpenCode、Cursor、Gemini CLI），并把安装逻辑改为登记表驱动。新工具只是**基础支持**（降级模式 + W 通道，档位不生效），目录来自官方文档检索，**未实机运行**。设计与后续路线见 `docs/design-more-hosts.md`。

### 宿主登记表 + install.sh 重写
- **改动**：新增 `adapters/hosts.tsv`（宿主、级别、专属目录、会读取的目录、检测命令/目录、下一步说明）和 `adapters/skill-dirs.tsv`（目录 key 与个人/项目路径）；`install.sh` 改为读登记表，`--host` 支持 `auto`（按命令或配置目录检测）、逗号列表、`all`（全部登记宿主）、`both`（兼容）；新增 `--layout minimal|per-host`（默认 minimal：贪心选能覆盖所选工具的最少目录，打平时优先单个工具的专属目录），`--list`、`--update`、`--uninstall`；每个副本写 `.hq-install.json`，个人范围写 `~/.hq/skill-path`；不在仓库内运行时（`curl | bash`）先用 git 下载 `v<版本>` 标签（`HQ_REF`、`HQ_REPO_URL`、`HQ_CACHE_DIR` 可覆盖）到 `~/.hq-orchestrator/`。新增退出码 4（没有可操作的对象）、5（下载失败）。保持 bash 3.2 兼容、只复制文件、先检查后写入。
- **行为变化**：`--host all` 从“claude、codex、dsh 三处”改为“全部登记宿主 + 最小集合”，即只装 `~/.agents/skills` 和 `~/.claude/skills`；要旧行为用 `--layout per-host`。
- **原因/假设**：多数工具已共用 `.agents/skills`、`.claude/skills`，分发不难，难在别重复装、别让用户自己查目录；登记表让新增宿主只需加一行。
- **验收指标**：`tests/test_install.sh` 全部通过（48 项，含新宿主、最小集合、auto、list/update/uninstall、引导下载、登记表自洽）；用户反馈的安装问题数 = 0；在 OpenCode、Cursor、Gemini CLI 各实测一次能发现并触发 hq 技能。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### 通用宿主文档与技能内的路径
- **改动**：新增 `skills/hq/references/hosts/generic.md`（OpenCode/Cursor/Gemini CLI/其他的识别表、能力表、档位记录方式 `tier:not-applied`、待核实项）；`SKILL.md` 第 1 步识别 opencode/cursor/gemini/other 并指向 generic.md，脚本查找先读 `~/.hq/skill-path` 再 find（路径加入 opencode/cursor/gemini 目录）；`hq-retro/SKILL.md` 同步；`metrics-schema.md` 的 host 取值加 `opencode`/`cursor`/`gemini`；`runtimes.md` 宿主索引更新；README 中英文更新安装说明并加入 `npx skills add`。
- **原因/假设**：装到新工具后，技能要能找到自己的脚本，并按统一方式记录 host，复盘才能按宿主比较。
- **验收指标**：3c 按宿主/通道 → opencode/cursor/gemini 的任务 host 字段都有值；缺记录任务数 = 0。
- **状态**：待验证
- **复盘报告**：无（人工改动）

---

## v0.3.2（2026-11-25）

### 低成本宿主拿不准时上调一档
- **改动**：`calibration.md` 新增规则 9：按实际计费方设成本系数（Claude Code 为 high；Codex、dsh、DeepSeek 后端为 low），low 宿主拿不准难度时（离上一档 ≤1 分、模糊度 ≥1，或在两档间犹豫）上调一档，最多一档；关键路径上的小任务或遇到限流时不上调；上调的任务在 notes 记 `bias:+1(cost_low)`。`playbook-template.md` 授权区新增 `cost_weight`；`hosts/codex.md`、`dsh.md`、`deepseek.md` 第 3 节引用此规则；README 中英同步。
- **原因/假设**：用户偏好。Codex 和 DeepSeek 的额度比 Claude 耐用，选高的边际成本低，用低档失败重来的代价相对更高；上调一档能提高一次通过率，而用时增加可以接受。
- **验收指标**：low 宿主上 notes 含 `bias:+1(cost_low)` 的任务 ≥5 个后，其一次通过率不低于同宿主未上调的任务，且 actual/est 中位数不高于后者的 1.5 倍；否则收回或缩小适用范围。
- **状态**：待验证
- **复盘报告**：无（用户偏好，人工改动）

## v0.3.1（2026-11-25）

本版本把 DeepSeek Harness（dsh）作为第三个原生宿主接入，DeepSeek 的推荐路径改为 dsh。dsh 部分**只读过官方仓库 deepseek-ai/deepseek-harness 提交 4b399c3 的文档，没有实机运行**，验证清单见 README“待核实项与本机验证清单”。

### dsh 宿主适配
- **改动**：新增 `skills/hq/references/hosts/dsh.md`（5 节、9 项能力：`subagent` 逐次传 provider/model/reasoning_effort，首次先 `list_subagent_models`；完成通知 + `list_agents` 监控；`send_message`；Schedule 做 schedule_checkin；stop_worker、worker_usage 待核实；外部后端不能选模型；并发取子代理树容量与 resources.sh 槽位较小值；W 通道暂不接入）。`hosts/deepseek.md` 改为三条路径，路径一（推荐）为 dsh，原两条顺延为路径二、三。`SKILL.md` 第 1 步加 dsh 识别特征，`SKILL.md` 与 `hq-retro/SKILL.md` 的 find 路径加 `~/.dsh/skills`、`.dsh/skills`。`calibration.md` 加 dsh 映射行（T0–T2 flash low/low/medium，T3–T4 pro medium/high），`runtimes.md` 宿主索引、`metrics-schema.md` host 取值加 `dsh`。
- **原因/假设**：dsh 每次派子代理都能指定模型和思考深度，五个档位能逐任务生效，比经 Claude Code（`CLAUDE_CODE_EFFORT_LEVEL`/`CLAUDE_CODE_SUBAGENT_MODEL` 可能覆盖档位、B 通道走 Claude 模型）或 Codex 接入更直接。
- **验收指标**：3c 按宿主/通道 → `dsh/A` 组有 ≥3 个任务时一次通过率 ≥ 70%；3a 按档位 → dsh 宿主下 T3/T4 一次通过率不低于 T0–T2；PLAYBOOK 有 dsh 映射行；缺记录任务数 = 0。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### install.sh：`--host dsh` 与 `--host all`
- **改动**：`install.sh` 的 `--host` 新增 `dsh`（个人范围 `${DSH_HOME:-~/.dsh}/skills`，项目范围 `<项目>/.dsh/skills`）和 `all`（三处都装）；`both` 保留作兼容（claude + codex）。usage 说明 dsh 也读 `~/.agents/skills`，装过 codex 不必重复装。`tests/test_install.sh` 补 dsh 个人/项目范围、`DSH_HOME`、`all`、`both` 兼容和 usage 说明的用例。
- **原因/假设**：让 dsh 用户一条命令装好；`all` 覆盖三种宿主，`both` 不破坏旧脚本。
- **验收指标**：`tests/test_install.sh` 全部通过；用户反馈的安装问题数 = 0。
- **状态**：待验证
- **复盘报告**：无（人工改动）

---

## v0.3.0（2026-11-25）

本版本让插件宿主无关：能在 Claude Code、Codex 上运行，并能通过这两者接入 DeepSeek 后端；其他工具走 W 通道或降级模式。Codex 和 DeepSeek 部分**都没有实机运行过**，验证清单见 README“待核实项与本机验证清单”。验收指标都能从 `metrics.py` 报告直接读出（“小节名 → 列名”），新增“3c. 按宿主/通道”小节。

### SKILL.md 宿主无关化与宿主文档
- **改动**：`skills/hq/SKILL.md` 只用抽象能力（spawn_worker、monitor、message_worker、stop_worker、worker_usage、schedule_checkin、remote_workers、local_machine、concurrency_limit）；第 1 步按特征识别宿主；具体调用移到 `references/hosts/{claude-code,codex,deepseek}.md`，`runtimes.md` 改为能力和通道总览。
- **原因/假设**：同一套流程能跑在多个宿主上，宿主差异集中在宿主文档里维护，SKILL.md 不再随某个宿主的工具名变化。
- **验收指标**：3c 按宿主/通道 → 每个有 ≥3 个任务的宿主组，一次通过率 ≥ 70%；质量门槛 → Claude Code 宿主的漂移率不高于 v0.2 同类运行；缺记录任务数 = 0。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### 抽象档位 + 宿主映射
- **改动**：`skills/hq/calibration.md` 档位改为与宿主无关的 T0–T4“所需能力”，另列各宿主映射；首次在新宿主上运行时把实际映射写进 PLAYBOOK“选档偏好”。数值和修正规则不变。
- **原因/假设**：不同宿主模型名不同，但难度分档逻辑相同；按宿主分开记录，复盘才能比较。
- **验收指标**：3a 按档位 → 各档一次通过率 ≥ 80%（与 v0.2 相同阈值，不因换宿主下降）；PLAYBOOK 中每个用过的宿主都有映射行。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### W 通道：CLI 子进程 worker（含 sandbox 闸门）
- **改动**：新增 `skills/hq/scripts/cli-worker.sh`（start/status/stop/usage/list），在 `.hq/worktrees/<id>` 里后台运行 `codex exec` 或 `claude -p`。sandbox 默认 `workspace-write`；`danger-full-access`（claude 为 `--dangerously-skip-permissions`）必须同时传 `--allow-dangerous`，否则退出码 2。codex 用量按 `turn.completed.usage` 计算：input 扣除 cached，output 已含 reasoning 不重复加，usage 为线程累计值。跨厂商 worker 须在 PLAYBOOK 授权区开启 `worker_clis`，默认关闭。测试 `tests/test_cli_worker.sh`（假 CLI）。
- **原因/假设**：没有子代理能力的宿主也能并行；需要真正的进程隔离时有选择；高风险权限不能因一个参数或默认值被打开。
- **验收指标**：3c 按宿主/通道 → `*/W` 组一次通过率 ≥ 70%、tokens 为 null 的比例 ≤ 20%；W 任务的漂移率 ≤ 10%。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### Codex 适配模板
- **改动**：新增 `adapters/codex/agents/hq-t0…hq-t4.toml` 和说明。字段（必填 name/description/developer_instructions，可选 model/model_reasoning_effort）和目录（`~/.codex/agents/`、`<项目>/.codex/agents/`）已按官方文档核对（2026-11-25），未实机运行；模型名是占位符。
- **原因/假设**：Codex 原生子代理按档位选 agent，比 W 通道开销小、能并行。
- **验收指标**：3c 按宿主/通道 → `codex/*` 组一次通过率 ≥ 70%；复盘时 codex 宿主的 PLAYBOOK 有完整 T0–T4 映射。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### DeepSeek 后端两条接入路径
- **改动**：新增 `references/hosts/deepseek.md`：路径一 Claude Code 接 DeepSeek（档位合成 flash/pro 两档，不设 `CLAUDE_CODE_SUBAGENT_MODEL`），路径二 Codex 接 DeepSeek。标注风险：官方建议的 `CLAUDE_CODE_EFFORT_LEVEL=max` 可能覆盖按档位设置的 effort（未下结论），`claude-code.md`、`calibration.md` 同步标注，task notes 记 `effort_env:max`；cost_usd 不可信，notes 记 `billing:deepseek`。
- **原因/假设**：用户想用更便宜的后端；flash/pro 两档加思考深度能覆盖 T0–T4。
- **验收指标**：DeepSeek 后端的 T3/T4 任务一次通过率 ≥ 70%（3a 按档位，按 notes 过滤）；带 `effort_env:max` 与不带的同档任务，平均 tokens 差异在复盘中有结论。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### 降级模式
- **改动**：`SKILL.md` 第 1 步：宿主没有子代理能力也用不了 W 时，主会话按同样的计划、台账、质量门槛串行亲自执行，channel 记 `main`；此时暂停铁律 1（不做重活），其余铁律照常。`PROMPT.md` 同步。
- **原因/假设**：在 OpenCode、Gemini CLI、Cursor 等工具里也能用同一套流程和数据记录。
- **验收指标**：3c 按宿主/通道 → `*/main` 组漂移率 ≤ 10%、缺记录任务数 = 0。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### install.sh
- **改动**：新增 `install.sh --host claude|codex|both [--scope user|project] [--with-codex-agents] [--force] [--dry-run]`：技能装到 `.claude/skills` 或 `.agents/skills`；agent 模板个人范围装到 `~/.codex/agents`，项目范围装到 `<项目>/.codex/agents`。先检查全部目标（含 agent 模板），已存在退出码 3，不装一半；不改任何配置。测试 `tests/test_install.sh`。
- **原因/假设**：多宿主的安装位置不同，手工复制容易放错。
- **验收指标**：用户反馈的安装问题数 = 0（复盘看 user_corrections 备注）；`tests/test_install.sh` 全部通过。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### 运行数据增加宿主维度
- **改动**：`metrics-schema.md` 的 task/run 增加可选字段 `host`；跨厂商 model 写成 `<cli>:<模型名>`；`metrics.py` 报告新增“3c. 按宿主/通道”；`/hq-retro` 复盘清单第 9 项做跨宿主、跨厂商对比（每组 ≥3 个任务才比较）。
- **原因/假设**：没有宿主维度就无法判断哪个宿主、哪条通道更划算。
- **验收指标**：3c 按宿主/通道 → `unknown/*` 组任务占比 ≤ 10%（新运行都应填 host）。
- **状态**：待验证
- **复盘报告**：无（人工改动）

## v0.2.0（2026-11-24）

本版本是一次整体升级，下面每条都是假设，还没有数据。v0.1 没有运行数据，所以验收指标都写成绝对阈值，不和 v0.1 比；所有指标都能从 `metrics.py` 报告直接读出（“小节名 → 列名”）。

### 要不要编排的判断
- **改动**：`skills/hq/SKILL.md` 新增“第 0 步：要不要编排”：预计不到约 30 分钟或高度耦合的工作不编排，直接在当前会话做。
- **原因/假设**：编排有固定成本（实测一个小子代理约 7.3 万 token 花在熟悉项目上），小任务开子会话得不偿失。
- **验收指标**：效率 → 任务数 ≤ 2 的 run 占比 ≤ 20%（这类 run 本应不编排）；自主性 → user_corrections 每任务 ≤ 0.1。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### 并行以总用时为准、小任务打包、难度单一
- **改动**：`skills/hq/SKILL.md` 第 2 步：以缩短关键路径为目标而不是并行数最多；小而相关的任务打包给一个子会话，约 15 分钟以上且文件不重叠才拆开；每个任务内部难度一致。
- **原因/假设**：每开一个会话都有启动成本；打包后总用时和成本都会下降，难度单一能减少中途调档。
- **验收指标**：效率 → 并行加速比 ≥ 1.3 且 wall/关键路径 ≤ 1.5；按档位 → 各档一次通过率 ≥ 80%；调档与检查点 → 升档任务数 / 总任务数 ≤ 15%。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### 按风险分级验证
- **改动**：`skills/hq/SKILL.md` 第 8 步“验证分级”（doc / code / high / e2e）和 `references/brief-template.md` 的“验证”节：子会话只做本级该做的验证，只有 high 级主会话才逐个复跑验收命令，全量测试在归并后统一跑一次。
- **原因/假设**：减少多余验证，同时不放过高风险任务的问题。
- **验收指标**：质量门槛 → 验证到位率 ≥ 90%、合并通过率 ≥ 90%、integration 问题/任务 ≤ 0.2（少验证的代价会先在合并环节暴露）。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### 选档移入 calibration.md，并算上失败重来的成本
- **改动**：打分表、档位表和修正规则从 `skills/hq/SKILL.md` 移到 `skills/hq/calibration.md`；新增规则 1（算上失败重来的成本）、规则 2（看不准先调研）、规则 6（不降档交接）。
- **原因/假设**：低档失败重来的总成本可能高于一次选对高档；复盘只调一个文件。
- **验收指标**：按档位 → 各档一次通过率 ≥ 80%、升档率 ≤ 15%；质量门槛 → 返工率 ≤ 10%。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### 动态调档与检查点
- **改动**：`skills/hq/SKILL.md` 第 7 步“动态调档”、`references/brief-template.md`“遇到问题时”、`references/runtimes.md`“建议用户手动调档”：子会话在超范围衍生、难度超预期、同一问题失败 2 次时发 CHECKPOINT；卡住时升一档新开会话从分支接着做；不做降档交接。
- **原因/假设**：尽早发现选档错误，减少整任务失败后重来。
- **验收指标**：调档与检查点 → 升档任务中有检查点的比例 ≥ 50%（近似“升档发生在检查点，而不是等失败之后”）；质量门槛 → 漂移率 ≤ 10%。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### 三项质量门槛
- **改动**：`skills/hq/SKILL.md` 第 8 步：把“不漂移、验证到位、问题少”定为质量门槛，审核和复盘（`skills/hq-retro/SKILL.md`）都以此为准；用时归入效率指标。
- **原因/假设**：用统一标准判断质量，优先于比时间和成本。
- **验收指标**：metrics 能稳定算出漂移率、验证到位率、各环节问题数（总览 → 缺记录任务数为 0 或 `-`，损坏行数为 0）；质量门槛 → 漂移率 ≤ 10%。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### 记录数据与复盘
- **改动**：`skills/hq/SKILL.md` 第 9 步：每个任务、每次运行往 `.hq/runs/<run_id>.jsonl` 追加记录；新增 `references/metrics-schema.md`（格式 v1，含用量口径：`cost_usd` 为主要成本指标，`tokens` 不含缓存读取）、`scripts/metrics.py`（只读汇总，同一任务重复记录只算一次）、`/hq-retro` 技能、`references/playbook-template.md`、本文件。
- **原因/假设**：用数据而不是印象改进插件，改动可追溯、可验证、可撤回。
- **验收指标**：总览 → 缺记录任务数 / 任务数 ≤ 5%、损坏行数为 0；连续 2 次复盘能从数据中得出至少 1 条通过证据门槛的结论或明确的“无建议”（看 `.hq/retro/` 报告）。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### 自主决策与停止条件
- **改动**：`skills/hq/SKILL.md` 铁律 2 和“自主决策与停止条件”：计划只通知不等确认，只有 3 类情况停下找用户，问题攒齐一次问；授权写在 PLAYBOOK“授权”区（`merge_default`、`open_pr`、`budget_usd`、`autonomy`）。
- **原因/假设**：减少不必要的打断，同时保证越权的事一定停下来。
- **验收指标**：自主性 → autonomy_stops / run 数 ≤ 1、user_corrections 每任务 ≤ 0.1；质量门槛 → major 数为 0（越权操作会表现为用户反馈的严重问题，原因写进 notes）。
- **状态**：待验证
- **复盘报告**：无（人工改动）

---

## v0.1.x（复盘后的小改进）

这三条来自 v0.1.0 实际运行后的人工复盘。当时还没有运行数据记录，所以只能等 v0.2 的数据来验证，状态都是“待验证”。

### 派 worktree 任务前检查忽略规则
- **改动**：`skills/hq/SKILL.md` 第 5 步（v0.2 起为第 6 步“派发”）：派 worktree 任务前确认 `.claude/worktrees/` 被 git 忽略，否则写入 `.git/info/exclude`；合并后清理 worktree 和临时分支。
- **原因/假设**：未被忽略时，子代理的临时目录显示为未跟踪文件，可能触发 hook 或被误提交。
- **验收指标**：之后的运行里，`notes` 写明由 worktree 目录未跟踪导致的问题数为 0（metrics 不单独统计，复盘时检索 notes）。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### 巡检间隔按预计时长设定
- **改动**：`skills/hq/SKILL.md` 第 6 步（v0.2 起为第 7 步“监控”）：巡检间隔取预计时长的 1 到 1.5 倍，最短 3 分钟，最长 30 分钟。
- **原因/假设**：固定间隔对小任务太长、对大任务太密，会空转或拖慢收尾。
- **验收指标**：效率 → wall/关键路径 ≤ 1.5（巡检太稀会拖慢收尾、拉高这个比值）。巡检次数本身不记录，太密的代价只体现在主会话消耗上，暂不量化。
- **状态**：待验证
- **复盘报告**：无（人工改动）

### 云端删除远程分支可能失败时交给用户
- **改动**：`skills/hq/SKILL.md` 第 7 步（v0.2 起为第 8 步“审核与归并”第 5 项）：云端 Git 通道删除远程分支失败时，试一次就停，把分支列在最终汇报里交给用户。
- **原因/假设**：云端通道可能不允许删分支，反复重试和绕路只会浪费时间。
- **验收指标**：行为规则，无量化指标。之后的运行里，`notes` 写明由反复重试删分支造成的问题数为 0（复盘时检索 notes）。
- **状态**：待验证
- **复盘报告**：无（人工改动）

---

## v0.1.0（初版）

### 司令部模式初版
- **改动**：新增 `/hq` 技能（`skills/hq/SKILL.md`）、`references/brief-template.md`、`references/runtimes.md`、`scripts/resources.sh`、中英文 README。
- **原因/假设**：由主会话统筹规划，按难度给子会话选模型和思考深度，按系统资源控制并发，审核后归并。
- **验收指标**：初版，无量化指标。由 v0.2 的数据记录接手评估。
- **状态**：已验证（能完成真实的多任务编排运行；`tests/test_resources.sh` 通过）
- **复盘报告**：无
