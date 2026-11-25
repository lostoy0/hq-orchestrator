# hq-orchestrator：司令部模式

中文 | [English](README.en.md)

在普通会话里（Claude Code 或 Codex，本地或云端都可以）实现类似 Projects 的工作方式：主会话负责统筹，子会话负责执行。主会话记录每次运行的数据，`/hq-retro` 用这些数据复盘，让插件越用越准。

**优化目标**：先过质量门槛（不漂移 + 验证到位 + 问题少），再求总用时最短，最后求成本最低。

## 支持的宿主（v0.4）

`SKILL.md` 只用抽象能力（spawn_worker、monitor 等），每个宿主的具体做法写在 `skills/hq/references/hosts/` 下。

| 宿主 | 宿主文档 | 状态 |
|---|---|---|
| Claude Code（本地 CLI、云端会话、桌面端、IDE） | `hosts/claude-code.md` | 主要宿主，v0.2 起实际使用 |
| Codex CLI | `hosts/codex.md` + `adapters/codex/` | agent 格式和目录已按官方文档核对（2026-11-25），**未实机运行** |
| **DeepSeek Harness（dsh）· DeepSeek 推荐路径** | `hosts/dsh.md` | 原生宿主：`subagent` 逐次指定 provider/model/思考深度；**只读过官方文档，未实机运行** |
| DeepSeek 后端 · 路径二：Claude Code 接 DeepSeek | `hosts/deepseek.md` | 档位压成 flash/pro 两档；云端子会话（B）仍用 Claude 模型 |
| DeepSeek 后端 · 路径三：Codex 接 DeepSeek | `hosts/deepseek.md` + `hosts/codex.md` | 配置示例来自官方摘要，待实测 |
| **OpenCode（V2）** | `hosts/opencode.md` + `adapters/opencode/` | v0.4.1 起原生宿主：`hq-t0…t4` 子代理各带 `provider/model#variant`，档位逐任务生效；**只读过官方文档，未实机运行** |
| **Gemini CLI** | `hosts/gemini.md` + `adapters/gemini/` + `gemini-extension.json` | v0.4.3 起原生宿主：`hq-t0…t4` 子代理各带 `model`（没有思考深度，只靠模型区分档位）；可作为 Gemini 扩展安装，带 `/hq`、`/hq-retro` 命令；**只读过官方文档，未实机运行** |
| Cursor（v0.4 起可一键安装） | `hosts/generic.md` | 基础支持：技能目录按官方文档登记，**未实机运行**；有 shell 用 W 通道，否则**降级模式**（主会话按同样的计划、台账和质量门槛串行亲自执行）。原生子代理适配见 `docs/design-more-hosts.md` |
| 其他支持 SKILL.md 的工具 | `hosts/generic.md` | 同上；可用 `npx skills add` 安装（见“安装”） |

## 包含什么
```
.claude-plugin/plugin.json             plugin 清单（v0.5.0）
.claude-plugin/marketplace.json        方便用 /plugin marketplace add 安装
skills/hq/SKILL.md                     核心流程：要不要编排 → 侦察 → 规划 → 选档 → 选位置 → 控并发 → 派发 → 监控与调档 → 审核归并 → 记录数据 → 汇报
skills/hq/calibration.md               选档校准表：5 维打分、T0–T4 档位、修正规则（复盘只调这个文件）
skills/hq/references/runtimes.md       抽象能力、派发通道（A/B/C/D/W）通用规则和宿主索引
skills/hq/references/hosts/*.md        各宿主的能力表、档位映射、安装调用、待核实项（claude-code / codex / dsh / opencode / deepseek / generic；kimi 为辅助执行者）
skills/hq/references/brief-template.md 子会话任务说明模板（含验证级别、检查点）与交付格式
skills/hq/references/metrics-schema.md 运行数据格式（JSONL，v1）和用量口径
skills/hq/references/playbook-template.md 项目经验手册 .hq/PLAYBOOK.md 的模板（含授权配置）
skills/hq/scripts/resources.sh         资源探测（Linux/cgroup/macOS），输出还能新开几个本地任务
skills/hq/scripts/metrics.py           把运行数据汇总成指标报告（只读）；--export-anon 按白名单脱敏导出
skills/hq/scripts/runs-persist.sh      把运行记录保存进仓库（专用分支 hq/runs 或当前分支）并取回
skills/hq/scripts/cli-worker.sh        W 通道：在独立 git worktree 里后台运行 codex / claude / opencode / gemini / cursor 的命令行
skills/hq/scripts/backends/*.sh        W 通道各 CLI 的参数拼装和用量解析（新增 CLI 加一个文件）
skills/hq-retro/SKILL.md               /hq-retro 复盘：验证上次改动、出有证据的建议、生成改插件的提示词
CHANGELOG.md                           每条改动的原因、验收指标和验证状态
PROMPT.md                              不装 plugin 时直接粘贴用的精简提示词
adapters/tiers.tsv                     档位登记表：T0–T4 的思考深度、模型档次、适合任务（子代理模板的唯一来源）
adapters/render.sh                     由 tiers.tsv 生成各宿主的 hq-t0…hq-t4 模板，可用 --model-map 填入模型
adapters/agent-dirs.tsv                子代理模板的安装目录登记表
adapters/codex/                        Codex 自定义 agent 模板 hq-t0…hq-t4（生成，模型名为占位符）
adapters/opencode/                     OpenCode V2 子代理模板 hq-t0…hq-t4（生成，默认不设 model）
adapters/gemini/                       Gemini CLI 子代理模板 hq-t0…hq-t4（生成，默认不设 model）
gemini-extension.json                  Gemini CLI 扩展清单：整个仓库可用 gemini extensions install 安装
commands/*.toml                        Gemini 扩展的 /hq、/hq-retro 命令（Claude Code 不读 .toml）
adapters/hosts.tsv                     宿主登记表：每个工具读哪些技能目录、怎么检测（新增宿主加一行）
adapters/skill-dirs.tsv                技能目录登记表：个人/项目范围路径
install.sh                             一键安装：自动检测工具、按最小目录集合复制技能，支持 --list/--update/--uninstall，不改任何配置
docs/design-more-hosts.md              支持更多宿主的设计草案与路线（v0.4.x）
tests/                                 resources.sh、cli-worker.sh、install.sh、runs-persist.sh、metrics.py 的自测
.github/ISSUE_TEMPLATE/retro-data.md   分享脱敏运行数据用的 issue 模板
```

## 安装

**方式 0：一行安装（推荐，所有宿主通用）**
```bash
curl -fsSL https://raw.githubusercontent.com/lostoy0/hq-orchestrator/v0.5.0/install.sh | bash -s -- --host auto
```
不在仓库里运行时，脚本先用 git 把 `v0.5.0` 标签下载到 `~/.hq-orchestrator/v0.5.0`，再执行安装（`HQ_REF=<标签或分支>` 可换版本）。想先看再跑：下载 `install.sh` 后用 `--list` 或 `--dry-run`。已 clone 本仓库的直接运行 `./install.sh`：
```bash
./install.sh --host auto|all|claude,codex,dsh,opencode,cursor,gemini [--scope user|project] [--project-dir <路径>]
             [--layout minimal|per-host] [--with-agents [--model-map 'T0=…,…,T4=…']] [--force] [--dry-run]
./install.sh --list          # 检测到的工具、已装副本和安装计划，不写入
./install.sh --update        # 把本脚本装过的副本更新到当前版本
./install.sh --uninstall     # 删除本脚本装过的副本
```
- `--host auto` 按命令（`claude`、`codex`、`opencode`、`cursor-agent`、`gemini`）或配置目录（`~/.claude`、`~/.codex`、`~/.dsh`、`~/.config/opencode`、`~/.cursor`、`~/.gemini`）检测本机装了哪些工具。`all` 为全部登记宿主；`both` 为旧写法，等同 `claude,codex`。
- **最小目录布局（默认）**：很多工具会读同一个目录，所以只装到能覆盖所选工具的最少目录，避免同一工具读到重复技能。全部工具时只装两处：

| 目录（个人 / 项目范围） | 读取它的工具 |
|---|---|
| `~/.agents/skills` / `<项目>/.agents/skills` | codex、dsh、opencode、gemini |
| `~/.claude/skills` / `<项目>/.claude/skills` | claude、opencode、cursor |
| 各工具专属目录（只装一个工具时使用） | `${DSH_HOME:-~/.dsh}/skills`、`~/.config/opencode/skills`、`~/.cursor/skills`、`~/.gemini/skills`（项目范围为 `.dsh/`、`.opencode/`、`.cursor/`、`.gemini/` 下的 `skills/`） |

  OpenCode 同时读前两个目录，Claude Code 和 Codex 都装时它会看到两份同名技能，按其规则只加载一份。`--layout per-host` 改为每个工具各装自己的专属目录（v0.3 的 `--host all` 行为）。
- `--with-agents`：同时安装所选宿主的子代理档位模板 `hq-t0…hq-t4`：Codex 装到 `~/.codex/agents/*.toml`，OpenCode 装到 `~/.config/opencode/agents/*.md`，Gemini CLI 装到 `~/.gemini/agents/*.md`（项目范围为 `<项目>/.codex/agents/`、`<项目>/.opencode/agents/`、`<项目>/.gemini/agents/`）。加 `--model-map 'T0=<模型>,…,T4=<模型>'` 会现场生成带真实模型的模板（一次只对一个宿主；Codex、Gemini 写模型名，OpenCode 写 `provider/model`，自动追加 `#low/#medium/#high`）。不加时 Codex 模板是占位符（必须替换），OpenCode、Gemini 模板不设 model（继承父会话模型，档位不生效）。旧写法 `--with-codex-agents` 仍可用。
  ```bash
  ./install.sh --host opencode --with-agents --model-map 'T0=<p/小模型>,T1=<p/中档>,T2=<p/中档>,T3=<p/最强>,T4=<p/最强>'
  ```
- 只复制文件，不改任何配置；每个副本里写 `.hq-install.json`（版本、来源、宿主），个人范围另写 `~/.hq/skill-path` 供技能找到自己的脚本。`--update`/`--uninstall` 只处理有安装记录的副本（v0.3 装的没有记录，用 `--host … --force` 重装一次即可纳入）。
- 退出码：0 成功；2 参数错误；3 目标已存在（加 `--force` 覆盖，或用 `--update`）；4 没有可操作的对象（未检测到工具、没有可更新/卸载的副本）；5 下载失败。会先检查所有目标，不会装一半。
- 宿主说明：Codex 的调用方式见 `hosts/codex.md`；dsh 的首次运行步骤见 `hosts/dsh.md`；OpenCode 见 `hosts/opencode.md`；Gemini CLI 见 `hosts/gemini.md`；Cursor 见 `hosts/generic.md`。

**方式 0a：Gemini 扩展**（只用 Gemini CLI 时最简单，带 `/hq`、`/hq-retro` 命令）
```bash
gemini extensions install https://github.com/lostoy0/hq-orchestrator --ref v0.5.0
```
扩展只含技能和命令，不含子代理模板（同一个仓库也是 Claude Code 插件，根目录放 `agents/` 会被 Claude Code 当成自己的子代理）。要让档位生效，再运行 `./install.sh --host gemini --with-agents --model-map 'T0=…,…,T4=…'` 安装模板；与扩展同时装了技能时，Gemini CLI 优先用用户目录的副本，安装脚本会提示。更新：`gemini extensions update hq-orchestrator`。

**方式 0b：社区通用安装器**（覆盖 70 多种代理工具，只装技能）
```bash
npx skills add lostoy0/hq-orchestrator                    # 交互选择工具
npx skills add lostoy0/hq-orchestrator -a opencode -a cursor
```
是否完整复制 `scripts/`、`references/` 待核实；缺脚本时资源检测和 W 通道不可用，此时请改用方式 0。

**方式 1：个人 skill（本地最简单）**
```bash
mkdir -p ~/.claude/skills && cp -r skills/hq skills/hq-retro ~/.claude/skills/
```
装好后在任意项目里输入 `/hq <目标>` 和 `/hq-retro` 即可使用。

**方式 2：作为 plugin 安装**（先把本目录推到你自己的 GitHub 仓库，或者放在本地某个路径下）
```
/plugin marketplace add <本地路径 或 owner/repo>
/plugin install hq-orchestrator@hq-orchestrator-marketplace
```
装好后用 `/hq-orchestrator:hq <目标>`、`/hq-orchestrator:hq-retro` 调用。

**方式 3：在云端会话中使用**

云端会话每次都在新容器里从仓库 clone 代码，**读不到你本机的 `~/.claude`**。所以本机用方式 0、1、2 装的东西（包括本机 `/plugin install` 装的插件）都不会带到云端。实测云端会话能用的 skill 和插件来自两处：目标项目仓库里提交的 `.claude/skills/`，以及 claude.ai 账号或组织里启用的插件。所以要让云端能用，skill 必须跟着**目标项目的仓库**走。

*推荐做法（云端已实测可用）：把 skill 复制进项目仓库。*
```bash
./install.sh --host claude --scope project --project-dir <项目路径>
# 或手动：mkdir -p .claude/skills && cp -r <本目录>/skills/hq <本目录>/skills/hq-retro .claude/skills/
```
提交 `.claude/skills/` 后，基于这个仓库新开的云端会话都能用 `/hq`、`/hq-retro`，辅助脚本（如 `scripts/resources.sh`）也能正常运行。好处是不依赖网络和 marketplace，还能锁定版本；坏处是每个项目一份副本，要逐个升级。

注意：`.hq/`（台账、运行记录、复盘报告）默认不提交，云端容器回收后就没了。要在云端跨会话复盘，在 `.hq/PLAYBOOK.md` 里设 `runs_persist: branch`（云端第一次运行结束时 `/hq` 也会问你一次）：每批结束后运行记录写进专用分支 `hq/runs`，不碰你的工作区和 main，`/hq-retro` 会自动取回。推不上这个分支时会自动改为 `commit`，跟本批改动一起提交。详见下文“运行记录与数据分享”。

*另一种做法：账号或组织级插件。* 想让所有云端会话都能用，可以在 claude.ai 的插件目录里给账号或组织启用它（前提是插件已在组织目录中，可能需要管理员上架）。

> ⚠️ **不要用项目 `.claude/settings.json` 声明插件来支持云端。** 用 `extraKnownMarketplaces` + `enabledPlugins` 声明 `hq-orchestrator@hq-orchestrator-marketplace` 的写法，2026-11 实测在云端**不会安装插件，也不报错**，skill 列表里没有 `hq-orchestrator:hq`。如果你照别处的教程这样配了却用不了，原因就在这里，改用上面的做法。

也可以用环境的 setup script 或 SessionStart hook 在每次开会话时运行 `install.sh`，但未实测，每次都要重装，还依赖环境配置，一般不如上面的做法省事。

**本地和云端同时用：避免重复安装**

| 情况 | 效果 | 建议 |
|---|---|---|
| 本机有个人副本（方式 0 或 1，`~/.claude/skills/hq`），项目里又提交了方式 3 的副本 | 本地在这个项目里会读到两个同名的 `/hq`，版本可能不同 | 用 `./install.sh --list` 看版本，两份保持同一版本最省事 |
| 本机既有个人副本，又用方式 2 装了插件 | 本地会同时出现 `/hq` 和 `/hq-orchestrator:hq`，名字不冲突，但模型可能选到任意一个；两份版本会慢慢不一致；插件版找辅助脚本时会先读 `~/.hq/skill-path`，可能用到个人副本里的旧脚本 | 二选一：只用插件就 `./install.sh --uninstall` 删掉个人副本；要在本地改插件、调试就保留，调试时明确用 `/hq` |

台账和运行记录（`.hq/`、`~/.claude/hq/runs/`）不受影响，两份 skill 写的是同一处，复盘照常。不确定本地是哪种安装时，可以运行 `./install.sh --list` 和 `ls ~/.claude/skills ~/.claude/plugins` 查看。

## 升级

先看已装的是哪个版本：`./install.sh --list` 会列出每个副本的路径和版本（读取副本里的 `.hq-install.json`）。然后按当初的安装方式升级，下面以 `v0.5.0` 为例，换成要升级到的版本即可。

| 安装方式 | 升级方法 |
|---|---|
| 方式 0（一行安装） | `curl -fsSL https://raw.githubusercontent.com/lostoy0/hq-orchestrator/v0.5.0/install.sh \| bash -s -- --update` |
| 方式 0（已 clone 仓库） | `git pull` 后运行 `./install.sh --update`；项目范围加 `--scope project --project-dir <路径>` |
| 方式 0a（Gemini 扩展） | `gemini extensions update hq-orchestrator` |
| 方式 0b（`npx skills add`） | 重新运行一次同样的 `npx skills add` 命令覆盖 |
| 方式 1（手动复制） | 拉取新版本后重新执行 `cp -r` 命令（会覆盖旧文件） |
| 方式 2（plugin） | `/plugin marketplace update hq-orchestrator-marketplace`，再在 `/plugin` 里更新 `hq-orchestrator`；本地路径添加的 marketplace 先在那个目录 `git pull` |
| 方式 3（项目仓库副本） | `./install.sh --update --scope project --project-dir <路径>`（或重新复制到 `.claude/skills/`）并提交 |

注意：

- `--update` 会把副本更新成**正在运行的这份脚本**的版本，不会自己联网查新版。所以一定要先拿到新版本的脚本（用新标签的一行命令，或先 `git pull`）。
- `--update` 只处理有安装记录的副本。v0.3 及更早装的、或手动复制的副本会被跳过并提示，用 `./install.sh --host <宿主> --force` 重装一次，以后就能正常 `--update`。
- `--update` **不更新子代理模板**（`--with-agents` 装的 `hq-t0…t4`）。新版本改了模板时（见 `CHANGELOG.md`），用原来的参数加 `--force` 重装：`./install.sh --host <宿主> --with-agents [--model-map '…'] --force`。注意 `--force` 会覆盖你手动改过的模板。
- 升级后重开会话，宿主才会读到新技能。

## W 通道与跨厂商 worker（默认关闭）

`skills/hq/scripts/cli-worker.sh` 在独立 git worktree（`.hq/worktrees/<id>`，分支 `hq/<id>`）里后台运行一个 CLI worker，任何有 shell 的宿主都能用：
```bash
cli-worker.sh start --id t2 --cli codex|claude|opencode|gemini|cursor --model <m> [--effort <e>] --brief <说明文件> [--sandbox read-only|workspace-write]
cli-worker.sh status|stop|usage --id t2      # 输出 JSON
cli-worker.sh list
```
- 各 CLI 的命令和沙箱映射见 `skills/hq/references/runtimes.md` 的 W 节。opencode、gemini、cursor 三个后端（v0.4.2）只按文档和源码写成、用假 CLI 测过，**未实机运行**；opencode 和 cursor 没有“只限工作区”的沙箱，`workspace-write` 也会放开 shell。
- sandbox 默认 `workspace-write`。`danger-full-access` 会关闭全部防护，**必须同时传 `--allow-dangerous`**，否则拒绝并以退出码 2 退出。
- `usage` 按统一口径算 tokens（input + output + cache_write，不含 cache_read）。
- 用和宿主不同厂商的 CLI 做 worker（跨厂商），需要在 `.hq/PLAYBOOK.md` 授权区写 `worker_clis`（如 `[codex, claude]`）；**默认为空，即关闭**。宿主自己的 CLI（如 Gemini CLI 宿主用 `--cli gemini`）不需要授权，这也是 Cursor、Gemini CLI 宿主让档位生效的方式。

## 辅助执行者：主模型主攻难点，Codex / Kimi 承接中低难度（v0.5.0，默认关闭）

大目标拆成很多子任务时，可以让主宿主只做难的、重要的任务，把需求明确的中低难度任务交给更便宜的模型，再由主宿主审核，以节省主宿主额度、增加并行度。**主宿主就是运行 hq 的那个宿主和模型**（Claude Code、Codex、Gemini CLI 等都可以），不一定是 Claude；辅助和主宿主是同一个（如在 Codex 里运行、`assist` 又写了 `codex`）时自动跳过。

- **怎么分**（`skills/hq/calibration.md` 规则 10）：只有档位 ≤ `max_tier`（默认 T2）、风险低、需求明确、一条命令就能验证对错、且不是共享接口这类前置任务的，才交给辅助；T3/T4、架构、安全、数据、并发、迁移、根因不明的问题和所有审核都留给主宿主。
- **怎么审**：辅助的产出一律由主宿主审核，不按“审核降一档”的规则降档；改动超过约 150 行另派独立审核。
- **失败怎么办**：辅助失败一次，就由主宿主高一档从它的分支接手。辅助**不可用**（CLI 起不来、未登录、限流、缺密钥）立即停用；**连续失败 2 次**或累计失败达到 `max_failures`（默认 2）也停用。所有辅助都停用后，本次剩余任务**全部由主宿主自己做**，不会停下来问你，只在汇报里说明一次。
- **怎么开**：
  ```
  /hq --assist codex,kimi <目标>            # 本次运行，按顺序优先
  /hq --assist kimi --assist-max T1 <目标>  # 只把 T0–T1 交出去
  /hq --assist off <目标>                   # 本次关闭
  ```
  长期设置写在 `.hq/PLAYBOOK.md` 授权区的 `assist`（`use`、`max_tier`、每个 profile 的 CLI、各档模型、可选 `env_file`），模板见 `skills/hq/references/playbook-template.md`。命令参数优先。
- **Kimi**：推荐经 `claude` CLI 接 Kimi 的 Anthropic 兼容接口，接口地址和密钥放在权限 600 的 `env_file` 里，`cli-worker.sh --env-file` 只把它注入这个 worker 进程，值不写进日志。见 `skills/hq/references/hosts/kimi.md`（**只按公开资料整理，未实机运行**）。
- **效果看数据**：task 记录多了 `assist` 字段，`metrics.py` 报告的“3d 辅助执行者 vs 主宿主”按档位对比一次通过率和回收率，`/hq-retro` 据此建议调低 `max_tier` 或停用某个辅助。
- **注意**：辅助走 W 通道，在本机（或云端容器）里运行，占本地 CPU 和内存；云端会话里要装好 CLI、放行接口主机、配好密钥，否则自动全部留给主宿主。外部模型失败重来会吃掉省下的额度，所以拿不准难度的任务不会交出去。

## 使用示例
```
/hq 给 api 服务加上导出 CSV 功能，并补齐测试和文档；前端改动要在我本机跑 e2e
```
主会话先判断值不值得编排（预计不到约 30 分钟或高度耦合的工作直接自己做），然后把计划（任务表、各任务的档位和模型、运行位置、并发数、预计用时）作为通知发给你，**不等确认就开始派发**。进度可以随时问，也可以直接查看 `.hq/LEDGER.md`。

## 常驻模式：让一个会话一直当总指挥

默认 `/hq <目标>` 只管一批。想在同一个会话里一批接一批地推进（比如会话已经有很多上下文，不想换新会话），用常驻模式：
```
/hq --stay 先把导出 CSV 做完
```
不给目标、只输入 `/hq --stay` 时，它会先探索项目（台账、路线图、TODO、open issue、最近提交、测试状态等；项目大时派只读子任务去看），给出带编号和来源的推荐任务，然后等你选：回复“做 1、3”只做选中的，回复“按推荐”全部做，或者直接说你自己的目标。进入时一定等你选，不会自动开始。没找到明确的待办时，它会说明查过哪些地方，请你给目标。

之后直接说下一个目标即可，例如“下一批：给导出加权限校验”。每批做完会汇报，末尾写“常驻中，等待下一个目标”；中间提问不会退出。

每批汇报后会自动推荐下一批（最多 5 条，每条附来源、预计档位和用时）。来源是台账待办、之前对话里没做完的事、项目里的路线图、TODO、open issue 和失败的测试。回复编号（如“做 1、3”）只做选中的，回复“按推荐”全部做。一条可执行的都没有、总目标也已达成时，它会明确说“项目当前所有任务都已执行完毕，没有更多可执行任务了”，并列出检查过哪些来源。它不会为凑数编任务；要密钥、部署或需要你操作的事单独列出，不算可执行任务。想让它不等回复按推荐一直做下去，就说“按推荐自动继续”（仍受预算和停止条件约束）。说“退出常驻”或 `/hq --stop` 结束。

**接管一个已经开着的会话**：会话启动后才装的技能，通常要重开会话才会出现在 `/hq` 里。不想重开时，在那个会话里输入下面这句（路径换成你的技能目录，可用 `find ~/.claude ~/.agents -path '*hq/SKILL.md'` 查找）：
```
读取 ~/.claude/skills/hq/SKILL.md 全文，按其中“常驻模式”接管本会话：先把我们之前对话里已做完的事和已定的决策写进台账“接管背景”，然后等我给目标。
```
没有文件访问权限的会话，把 `PROMPT.md` 整段粘进去，再说“常驻”。

注意：
- 主会话会把技能路径记在 `.hq/LEDGER.md` 头部（`skill_path`），上下文被压缩后自己重读技能和台账。万一发现它开始亲自干活、不再派子会话，说一句“重新读取 SKILL.md，继续常驻”即可。
- 子会话看不到聊天记录，所以接管时之前的进度要写进台账“接管背景”。以后即使必须换新会话，也只要让新会话读 SKILL.md 和台账就能接上。
- 每批仍会先判断值不值得编排，小目标会直接自己做；要强制派发就在目标里写“这批也全部派出去”。

## 自主执行与停止条件
- 技术方案、模型、拆分、重试都由主会话自己决定，每个决策记进台账“决策”区。
- 只有三种情况会停下来找你，问题攒齐一次问，每个附推荐选项，同时继续推进不受影响的工作：
  1. 需要密码、密钥、账号、付款，或需要你在界面上、在自己电脑上操作；
  2. 不可撤回或影响别人的操作且没有事先授权：删除数据或分支、部署、强制推送、对外发布、超出预算；
  3. 需求有歧义，调研后仍判断不了，且猜错的返工代价超过约 1 小时。
- 推送 `hq/*` 分支、合并到 `hq/integration` 默认自动；合入默认分支、开 PR 默认要问。

## 授权配置
写在项目的 `.hq/PLAYBOOK.md`“授权”区（模板见 `skills/hq/references/playbook-template.md`），一次设定、之后不再逐次询问：
```yaml
merge_default: ask        # ask | auto-if-gates-pass：质量门槛都通过时是否自动合入默认分支
open_pr: ask              # ask | auto
budget_usd: 20            # 单次运行的花费上限，超出前停下来问
autonomy: auto            # auto | confirm-plan：confirm-plan 时计划要等你确认再派发
worker_clis: []           # 跨厂商 worker，可选 codex/claude/opencode/gemini/cursor；默认空即关闭
runs_persist: off         # off | branch | commit：运行记录是否保存进仓库；云端没写时问一次
```

## 进化闭环：记录 → 复盘 → 改插件
1. **记录**：每个任务结束、每次运行结束，主会话往 `.hq/runs/<run_id>.jsonl` 追加一行（格式见 `metrics-schema.md`，记录 `host`；本地运行时另存一份到 `~/.claude/hq/runs/`，Codex 宿主也用这个目录）。成本以 `cost_usd` 为主，`tokens` 不含缓存读取。
2. **复盘**：累计约 5 次运行或 20 个任务时，主会话会提示你运行 `/hq-retro`。它用 `metrics.py` 出指标报告，先按 `CHANGELOG.md` 的验收指标核对上次改动，再交给独立子代理出有证据的建议（至少 3 个任务或 2 次运行出现才算）。只与本项目有关的经验直接写进 `.hq/PLAYBOOK.md`。
3. **改插件**：涉及插件本身的建议由你把关。报告最后附一段提示词，你复制到 hq-orchestrator 仓库的会话里执行，它会改文件、跑测试、在 `CHANGELOG.md` 记一条“待验证”并升补丁版本号。下一次复盘再验证它，没达标就撤回。

## 运行记录与数据分享

**保存运行记录**（PLAYBOOK `runs_persist`）

| 取值 | 做法 | 适合 |
|---|---|---|
| `off` | 只写本地 `.hq/runs/`（本地运行另存 `~/.claude/hq/runs/`） | 只在本地用 |
| `branch` | 每批结束后 `runs-persist.sh save branch`：把记录写进专用分支 `hq/runs` 的 `runs/` 下并推送；只追加，多个会话同时写不冲突，不碰工作区和当前分支 | 云端（推荐） |
| `commit` | `runs-persist.sh save commit`：只把记录文件提交到当前分支，随本批改动一起推 | 推不上 `hq/runs` 时自动降级到这里 |

`/hq-retro` 会先运行 `runs-persist.sh fetch` 把 `hq/runs` 上的记录取到 `.hq/runs-archive/`，再和本地记录一起汇总（同一次运行只算一次）。`hq/runs` 是独立的历史分支，不要合并进别的分支。

**分享数据，帮助改进插件**（完全自愿，不会自动上传）

1. 运行 `/hq-retro --export`。它用 `metrics.py --export-anon` 按白名单导出：只保留档位、模型、通道、用时、成本、通过率这类枚举和数字字段，删掉所有自由文本（任务标题、目标、备注、验证输出）和项目名，run_id 做哈希，时间只留日期。白名单见 `metrics-schema.md`。
2. 导出内容会完整显示给你，并保存到 `.hq/retro/export-<日期>.json`。
3. 愿意分享的话，用 [retro-data 模板](https://github.com/lostoy0/hq-orchestrator/issues/new?template=retro-data.md) 新建 issue 并贴上。issue 是公开的，贴之前请再看一遍。

`/hq-retro` 只会在第一次复盘的报告末尾提示一次这件事（记在 PLAYBOOK 的 `share_hint`），之后不再提。

## 设计要点
- **要不要编排**：编排有固定开销，小任务不开子会话。
- **并行以总用时为准**：优先缩短关键路径；小而相关的任务打包，大任务且文件不重叠才拆开。
- **难度分档**：按 `calibration.md` 5 维打分得到抽象档位 T0–T4，再按宿主映射成具体模型（Claude Code 为 haiku/low 到 opus/high）；选档算上失败重来的成本，看不准先调研。拿不准难度时自动往上选一步（`calibration.md` 规则 9）：Codex、dsh、DeepSeek 后端额度更便宜，上调一整档；Claude Code 默认只把思考深度上调一级，需求模糊或高风险时上调一整档（可在 PLAYBOOK 的 `cost_weight` 调整）。
- **动态调档**：子会话遇到超范围衍生任务、难度超预期或反复失败时发检查点；卡住就升一档新开会话从分支接着做，不做降档交接。
- **运行位置路由**：需要本地资源的任务一定在本地跑，能并行的长任务放到云端，小任务在进程内执行。
- **资源保护**：每次派发前都检测资源，按 GREEN/YELLOW/RED 三级控制派发；给子会话限定构建并行度；RED 时停掉最新启动的重任务。
- **质量把关**：三项质量门槛；验证按风险分 doc/code/high/e2e 四级，只有 high 级主会话才逐个复跑验收命令，归并后统一跑一次全量测试；高风险或大改动另派独立审核者。
- **可恢复**：所有状态写在台账里，上下文被压缩或会话重启后可以接着做。

## 自测
```bash
for t in tests/test_resources.sh tests/test_cli_worker.sh tests/test_install.sh tests/test_runs_persist.sh; do echo "$t: $(bash $t | tail -1)"; done
python3 -m unittest discover tests
```
`test_cli_worker.sh` 用 `tests/fixtures/fake-cli/` 下的假 `codex`、`claude`、`opencode`、`gemini`、`cursor-agent` 测参数拼接和用量解析，不调用真实 CLI。
`resources.sh` 支持 `HQ_FAKE_CORES`、`HQ_FAKE_LOAD1`、`HQ_FAKE_MEM_TOTAL_MB` 等环境变量注入模拟读数，用来覆盖 GREEN/YELLOW/RED 各种情况。

## 待核实项与本机验证清单

本仓库的开发环境装不了 codex 和 dsh，下面这些需要你在本机实测。结果请写进项目 `.hq/PLAYBOOK.md`（宿主映射）或提 issue。

**待核实**（详见各宿主文档第 5 节）：
- Codex：`codex exec` 的 `-m`、`-c model_reasoning_effort=…`、`-s` 写法；agent 模板实际能否被加载；并发上限配置名；`codex cloud` 能否指定 model/effort；原生子代理的监控、中止和用量读取。
- dsh：桌面端子代理模型路由设置的位置；并发上限配置键；非交互 CLI 命令（能否做 W 通道 worker）；`reasoning_effort` 取值范围；用量和成本的读取方式；中止子代理的方式；Schedule 的工具名。
- DeepSeek（路径二、三）：`CLAUDE_CODE_EFFORT_LEVEL=max` 是否覆盖 hq 按档位设的 effort；`ANTHROPIC_DEFAULT_OPUS_MODEL` 能否设为 `deepseek-v4-pro`；`deepseek-flash` 与 `deepseek-v4-flash` 是否等价。
- Claude Code：本地 CLI 发起云端任务（通道 D）的参数。
- OpenCode（v0.4.1 原生宿主）：`hq-t*` 子代理能否被识别、各档 `model#variant` 能否解析；中止子代理的方式；`opencode session export` 里的 token/成本字段；多个后台子代理同时运行时的权限审批。
- W 通道新后端（v0.4.2）：`opencode run`、`gemini -p`、`cursor-agent -p` 在本机各跑一次 `start/status/usage/stop`，核对参数是否被接受、`usage` 是否有 tokens（cursor 的用量字段名未知）；gemini `auto_edit` 下能否跑 shell 命令。
- Gemini CLI（v0.4.3 原生宿主）：`gemini extensions install` 能否装上、`/hq` 能否激活技能；`hq-t*` 子代理能否加载、模型能否生效；同一轮多个子代理调用能否并行；子代理用量的读取方式；Claude Code 装插件后 `commands/*.toml` 不应出现为命令。
- Cursor（v0.4 基础支持）、Gemini CLI：`--host auto` 装好后各工具能否发现并触发 hq 技能；Cursor 是否也读 `~/.agents/skills`；`npx skills add` 是否带上 `scripts/` 和 `references/`。

**装好 codex 后运行，核对参数**：
```bash
codex --version
codex exec --help | grep -nE -- '-m|--model|-c|--config|-s|--sandbox|--json'   # 核对 cli-worker.sh 用到的参数
./install.sh --host codex --with-codex-agents                                  # 再替换 ~/.codex/agents/hq-t*.toml 的 model 占位符
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
- Codex 适配、dsh、DeepSeek 后端以及 OpenCode/Cursor/Gemini CLI 都还没有实机运行数据，见上一节。Cursor 目前只是基础支持，档位不生效；OpenCode、Gemini CLI 的子代理和主会话共用工作目录，改代码的任务靠 hq 先建 worktree 隔离。
- 本地 CLI 能否直接创建云端子会话，取决于 CLI 版本（见 runtimes.md 的通道 D）。这类子会话监控能力较弱。需要强监控时，把主会话放在云端，再通过“连接电脑”处理本地任务。
- 进程内子代理和主会话共享同一台机器，资源保护只能控制派发节奏，没法限制子代理自己调用的进程。所以任务说明里的并行度限制很重要。
- 进程内子代理的返回结果只有 token 总数、分不出缓存读取，这类任务的 `tokens` 记为空，成本比较以云端子会话的 `cost_usd` 为主。
- 难度分档表是经验默认值，可以按你的账户和实际体验在 `skills/hq/calibration.md` 里调整；更推荐用 `/hq-retro` 按数据调整。
