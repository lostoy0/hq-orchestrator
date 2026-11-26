---
name: hq-design
description: HQ 设计阶段。仅在用户显式输入 /hq-design 时使用：根据需求文档（以及竞品调研、品牌素材、现有前端代码）按上线标准产出设计规范、页面与流程说明、可离线打开的高保真可点击原型（含模拟账号和模拟数据，主要流程能从头点到尾，每页都有空、加载、错误等状态），并自动走查截图；已有设计就评审后补全；交付前由产品、开发、测试评审，评审轮次有上限。用户只是提到“设计”“原型”时不要自动使用。
argument-hint: "[补充说明] [--platform web|ios|android|mini] [--explore N] [--brand <文件或说明>] [--scope <模块或页面>] [--figma] [--convert] [--ask] [--review-only] [--rounds N] [--panel 角色,…]"
disable-model-invocation: true
license: "Apache-2.0 with Commons Clause v1.0 (https://github.com/lostoy0/hq-orchestrator/blob/main/LICENSE)"
---

# HQ 设计阶段（/hq-design）

做出一个**像上线产品一样能从头点到尾**的高保真原型：真实的页面、真实的流程、模拟的账号和数据、每种状态都有，配一份设计规范和页面流程说明。原型是给人体验和评审用的，不是产品代码；开发时照着它做。

## 先读

1. 找 hq 技能目录 `<hq>`：本文件同级的 `../hq/`（里面有 `SKILL.md`）；没有就读 `~/.hq/skill-path`；再没有就用 shell 查找：`find ~/.claude/skills ~/.claude/plugins ~/.agents/skills ~/.dsh/skills ~/.config/opencode/skills ~/.cursor/skills ~/.gemini/skills ~/.gemini/extensions/hq-orchestrator/skills .claude/skills .agents/skills .dsh/skills .opencode/skills .cursor/skills .gemini/skills -path '*hq/SKILL.md' 2>/dev/null | head -1`，取其目录。
2. 读 `<hq>/SKILL.md`（主流程：本次运行按它执行）、`<hq>/references/stages/common.md`（阶段通用规则）、`<hq>/references/roles/designer.md`，以及本文件同级的 `prototype-schema.md`（原型清单格式）、`template-design-system.md`、`template-screens.md`，浏览一遍 `prototype-starter/`（原型起步套件）。
3. 台账头部写 `stage: design`。

## 参数

- 命令后面的文字：补充说明（如“偏商务风”“主色用品牌绿”“只做手机端”），作为约束写进台账头部和设计规范第 1 章。
- `--platform`：`web`、`ios`、`android`、`mini`（小程序）。没给时按需求文档判断，判断不出用 `web`。
- `--explore N`：先做 N 个风格方向（每个只做入口页和一个核心页），选定一个再铺开。默认 1（不探索）；全新产品、没有品牌素材时建议 `--explore 3`。
- `--brand <文件或说明>`：品牌素材（logo、主色、字体、已有设计稿）。
- `--scope <模块或页面>`：只新做或补全某个模块的页面，其余只做一致性检查。
- `--convert`：已有可点击原型不是本格式时，按本格式重做（默认是接管）。
- `--figma`：连了 Figma 的 MCP 时，把定稿的页面截图推送到 Figma 供标注和讨论；默认不推送。
- `--ask`、`--review-only`、`--rounds N`、`--panel 角色,…`：见 `common.md` 第 4–6 节。默认评审团：`pm`、`engineer`、`qa`。

## 1. 输入

在 `docs_root`（`common.md` 第 2 节）和仓库里找：需求文档、竞品调研、品牌素材、已有设计稿或原型、现有前端代码（样式变量、组件库、页面）。

| 情况 | 做法 |
|---|---|
| 有需求文档 | 正常设计；先运行 `doc-check.py prd`，有错误照常设计，把错误列进“假设与待确认” |
| 只有想法或截图，没有需求文档 | 可以设计，但侦察任务先整理出功能清单（写进页面与流程说明的“假设与待确认”，注明“需求未经评审”）；汇报里建议运行 `/hq-prd` |
| 已有原型（`design/prototype/manifest.js`） | 补全模式：先跑两个检查脚本和视觉走查，按完成标准列缺项，只增改不删；已有页面编号不改 |
| 已有能点击的原型，但不是本格式（别的工具生成的 HTML 原型等） | 按 `common.md` 第 10 节**接管**：先建或读对应表 `hq-artifacts.json`，再做接管评审（按完成标准判断内容，不看格式），把结果用 `stage-status.py --record-audit` 记下；已冻结的只写提案，没冻结的在原文件里按原结构补缺口，编号照用；评审时用浏览器逐页打开、走主要流程、切换状态（有 Playwright 就截图），对照第 4 节完成标准。只有带 `--convert` 时才按本格式重做 |
| 只有静态设计稿（图片、Figma 链接） | 当作视觉参考：侦察任务描述出页面、风格和组件，按本格式做原型，风格尽量延续；原文件不动 |
| 已有前端代码 | 原型沿用代码里的颜色、字体、间距和组件样式（抄进 `tokens.css`），保证开发时照做不走样 |
| 什么都没有，命令后面也没写 | 问用户一句：“要设计的产品是什么？一两句话描述，或给需求文档路径。”这是本阶段唯一需要等用户的输入 |

## 2. 任务图（hq 主流程第 2 步按这个模板拆）

开始前，主会话把 `prototype-starter/` 整个复制到 `<docs_root>/design/prototype/`（已有原型时跳过），改好 `manifest.js` 的 `product` 和 `platform`。

| 步 | 内容 | kind | 典型档位 | 依赖 |
|---|---|---|---|---|
| g1 侦察 | 只读：从需求推出要哪些页面（每个有界面的 F- 落在哪页）、核心流程、角色；竞品里值得借鉴的交互；品牌素材和现有代码的样式 | research | T2 | - |
| g2 页面与流程 | 写 `design/screens.md`（页面清单、导航图、核心流程、演示账号、模拟数据结构），并写好 `manifest.js` 的 `pages`、`flows`、`accounts`（页面文件先不写） | docs | T3 | g1 |
| g3 风格 | 定设计方向，改 `assets/tokens.css`（必要时调整 `base.css` 的组件样式），写 `design/design-system.md`。`--explore N` 时先并行做 N 个方向（每个方向一个任务，只做入口页和一个核心页，放在 `design/explore/<n>/`），主会话按第 3 节选定一个，理由写进设计规范第 1 章 | docs | T3（探索的每个方向 T2） | g1 |
| g4 模拟数据 | 按 `screens.md` 第 5 章写 `data/seed.js` | code | T1 | g2 |
| g5 页面 | 按流程分组并行，每个任务负责一组页面文件（归属不重叠）；共享的 `assets/` 和 `seed.js` 只读，缺组件或数据就在交付里写 DERIVED，由主会话派给 g3 或 g4 的负责人补 | code | T2（交互复杂的页面 T3） | g2、g3、g4 |
| g6 检查与走查 | 主会话运行 `python3 <hq>/scripts/prototype-check.py <原型目录> --prd <需求文档>` 和 `node <hq>/scripts/prototype-walk.mjs <原型目录> --out <docs_root>/design/screens`，把失败项交回对应页面的负责任务修，直到没有错误 | - | - | g5 |
| g7 视觉走查 | 只读：`designer` 角色逐张看 g6 的截图，按第 3 节和设计规范列出问题（对齐、间距、层级、一致性、状态是否像样、像不像通用 AI 风格），交回页面任务修改 | review | T2 | g6 |
| g8 评审 | 评审团并行，按 `common.md` 第 5 节；说明里附原型打开方式、演示账号和截图目录 | review | 按角色卡 | g7 |
| g9 修改与复核 | 按分诊结果修改，再跑一次 g6；第 1 轮有 blocker 或 major 时做第 2 轮评审 | code / review | 同 g5 / g8 | g8 |

- 产品小（页面少于约 6 个）时，g4、g5 合成一个任务。
- 没有 Playwright（`prototype-walk.mjs` 退出码 3）时，g6 只跑静态检查，g7 改为在宿主的浏览器工具里手动打开主要页面截图；都做不到时在评审记录里写明“未自动走查”。
- 带 `--figma` 且连了 Figma 时，g9 之后把截图按流程顺序推送到一个新的 Figma 文件（按 Figma 技能的要求先建会话），文件链接写进汇报。

## 3. 设计规则（写进 g3、g5、g7 的说明）

**默认方向：简洁易懂，又现代好看**
- 一屏一个主要操作，其他操作降级成次要按钮或收进菜单；信息按重要程度分层，用字号、字重、颜色深浅区分，不靠边框和底色堆层级。
- 留白充足，间距只用 4 的倍数（`--space-*`）；同类元素对齐到同一条线。
- 颜色克制：一个主色加中性灰，语义色只用于状态（成功、警告、危险）；不用大面积渐变。
- 字号不超过 4 级，字重不超过 2 种；正文 16px 起（手机 15–17px），行高 1.5。
- 图标用一套线性风格的内联 SVG，粗细一致；不用 emoji 当图标。
- 动效只用来解释变化（出现、展开、反馈），时长 120–200ms，尊重“减少动态效果”设置。
- **避免一看就是 AI 生成的样子**：满屏卡片套卡片、处处圆角加阴影、紫色渐变、玻璃拟态、装饰性的大插图、每个标题配 emoji、无意义的统计数字和占位文案。
- `--explore` 选方向时，按“用户能不能一眼看懂 > 和品牌、现有产品一致 > 好看”的顺序选。

**每个页面**
- 只用 `tokens.css` 的变量和 `base.css` 的组件；新组件先加到 `base.css`（找 g3 的负责人），不在页面里写死颜色和尺寸。
- `manifest.js` 里声明的每种状态都要做出来，而且要像样：空状态有说明和引导操作，加载用骨架屏，错误说清发生了什么、给重试，无权限说明原因和出路，首次使用有简短引导。
- 交互要完整：表单有校验和就地报错，提交有加载和成功反馈，危险操作二次确认或可撤销，返回和取消都有去处，列表有大量数据和超长文本时不变形。
- 文案用产品自己的口吻，按设计规范第 5 章写；不用“Lorem ipsum”和“示例文本”。
- 页面之间用 `<a href="其他页面.html">` 跳转（静态检查能顺着链接走）；需要点击、输入的元素加 `data-testid`。
- 数据都走 `HQ.api()` 和 `HQ.db`（模拟接口和本地数据），这样状态切换和自动走查才有效。

**流程与账号**
- 每个 P0、P1 用户旅程写成一条 `flow`，包括注册、登录、找回密码这类基础流程（需求里有的话），从入口一直点到完成。
- 演示账号覆盖每种角色和关键状态：首次使用的新用户（`first: true`）、有数据的老用户、付费用户、管理员等（按需求）。
- 模拟数据要像真的：虚构但合理的名字、金额、时间、长短不一的文本，覆盖空值和大量数据；不用真实人员的信息。

## 4. 完成标准（自检和评审都按这个清单）

1. `prototype-check.py`（带 `--prd`）没有错误；每条警告都已改掉，或在“假设与待确认”里写明理由。
2. `prototype-walk.mjs` 全部通过：每页每种状态都能打开、没有控制台报错，每条流程从头走到尾；截图在 `design/screens/`。没有 Playwright 时写明替代的检查方式。
3. 每个有界面的 P0、P1 功能都有页面；每个 P0 功能都有流程覆盖；注册登录等基础流程（需求里有的）能走通。
4. 每页的空、加载、错误、无权限、首次使用状态要么做了且像样，要么在 `na` 里写了原因。
5. 演示账号覆盖所有角色和关键状态；模拟数据像真的，覆盖边界。
6. 视觉走查（g7）提出的问题都已处理；整套页面风格一致，只用设计变量；没有第 3 节列出的 AI 风格问题。
7. 可访问性：对比度、可点区域、键盘操作和焦点、不只靠颜色传达信息。
8. 设计规范和页面与流程说明写全，和 `tokens.css`、`manifest.js` 一致。
9. 原型能离线打开（双击 `index.html`，或 `python3 -m http.server`），不依赖外部网络资源。
10. 评审：没有未解决的 blocker；评审记录已写进 `reviews/design-<YYYYMMDD>.md`。

## 5. 交付与汇报

- 产物（`design/design-system.md`、`design/screens.md`、`design/prototype/`、`design/screens/`）在 `hq/<任务id>` 分支上，按 PLAYBOOK 授权合并（`common.md` 第 1 节）。
- run 记录写 `common.md` 第 8 节的阶段字段。
- 汇报（按 hq 主流程第 10 步，再加以下内容）：
  - 打开方式：`python3 -m http.server 8000 -d <docs_root>/design/prototype` 后访问 `http://localhost:8000`，或直接双击 `index.html`；演示账号列表。
  - 3–5 张关键截图（入口、核心流程、一个状态页）；设计方向一句话；页面数、流程数、走查结果。
  - 评审轮次、各级问题数、未解决项；待决定事项 `D-xx` 和其他假设。
  - 下一步：运行 `/hq-arch` 做技术设计，或已有架构时运行 `/hq-plan`。
