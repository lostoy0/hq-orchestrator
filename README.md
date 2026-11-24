# hq-orchestrator：司令部模式

中文 | [English](README.en.md)

在普通会话里（本地 CLI 或云端会话都可以）实现类似 Projects 的工作方式：主会话负责统筹，子会话负责执行。主会话记录每次运行的数据，`/hq-retro` 用这些数据复盘，让插件越用越准。

**优化目标**：先过质量门槛（不漂移 + 验证到位 + 问题少），再求总用时最短，最后求成本最低。

## 包含什么
```
.claude-plugin/plugin.json             plugin 清单（v0.2.0）
.claude-plugin/marketplace.json        方便用 /plugin marketplace add 安装
skills/hq/SKILL.md                     核心流程：要不要编排 → 侦察 → 规划 → 选档 → 选位置 → 控并发 → 派发 → 监控与调档 → 审核归并 → 记录数据 → 汇报
skills/hq/calibration.md               选档校准表：5 维打分、T0–T4 档位、修正规则（复盘只调这个文件）
skills/hq/references/runtimes.md       各派发通道的具体用法、用量读取、建议用户手动调档的话术
skills/hq/references/brief-template.md 子会话任务说明模板（含验证级别、检查点）与交付格式
skills/hq/references/metrics-schema.md 运行数据格式（JSONL，v1）和用量口径
skills/hq/references/playbook-template.md 项目经验手册 .hq/PLAYBOOK.md 的模板（含授权配置）
skills/hq/scripts/resources.sh         资源探测（Linux/cgroup/macOS），输出还能新开几个本地任务
skills/hq/scripts/metrics.py           把运行数据汇总成指标报告（只读）
skills/hq-retro/SKILL.md               /hq-retro 复盘：验证上次改动、出有证据的建议、生成改插件的提示词
CHANGELOG.md                           每条改动的原因、验收指标和验证状态
PROMPT.md                              不装 plugin 时直接粘贴用的精简提示词
tests/                                 resources.sh 和 metrics.py 的自测
```

## 安装

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
云端容器里没有你本机的 `~/.claude`，所以要把 skill 放进项目仓库：
```bash
mkdir -p .claude/skills && cp -r <本目录>/skills/hq <本目录>/skills/hq-retro .claude/skills/ && git add .claude/skills
```
提交后，基于这个仓库新开的云端会话都能用 `/hq`、`/hq-retro`。也可以在云端会话里用方式 2 的 marketplace 安装。

## 使用示例
```
/hq 给 api 服务加上导出 CSV 功能，并补齐测试和文档；前端改动要在我本机跑 e2e
```
主会话先判断值不值得编排（预计不到约 30 分钟或高度耦合的工作直接自己做），然后把计划（任务表、各任务的档位和模型、运行位置、并发数、预计用时）作为通知发给你，**不等确认就开始派发**。进度可以随时问，也可以直接查看 `.hq/LEDGER.md`。

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
```

## 进化闭环：记录 → 复盘 → 改插件
1. **记录**：每个任务结束、每次运行结束，主会话往 `.hq/runs/<run_id>.jsonl` 追加一行（格式见 `metrics-schema.md`；本地运行时另存一份到 `~/.claude/hq/runs/`）。成本以 `cost_usd` 为主，`tokens` 不含缓存读取。
2. **复盘**：累计约 5 次运行或 20 个任务时，主会话会提示你运行 `/hq-retro`。它用 `metrics.py` 出指标报告，先按 `CHANGELOG.md` 的验收指标核对上次改动，再交给独立子代理出有证据的建议（至少 3 个任务或 2 次运行出现才算）。只与本项目有关的经验直接写进 `.hq/PLAYBOOK.md`。
3. **改插件**：涉及插件本身的建议由你把关。报告最后附一段提示词，你复制到 hq-orchestrator 仓库的会话里执行，它会改文件、跑测试、在 `CHANGELOG.md` 记一条“待验证”并升补丁版本号。下一次复盘再验证它，没达标就撤回。

## 设计要点
- **要不要编排**：编排有固定开销，小任务不开子会话。
- **并行以总用时为准**：优先缩短关键路径；小而相关的任务打包，大任务且文件不重叠才拆开。
- **难度分档**：按 `calibration.md` 5 维打分，T0 到 T4 对应 haiku/low 到 opus/high；选档算上失败重来的成本，看不准先调研。
- **动态调档**：子会话遇到超范围衍生任务、难度超预期或反复失败时发检查点；卡住就升一档新开会话从分支接着做，不做降档交接。
- **运行位置路由**：需要本地资源的任务一定在本地跑，能并行的长任务放到云端，小任务在进程内执行。
- **资源保护**：每次派发前都检测资源，按 GREEN/YELLOW/RED 三级控制派发；给子会话限定构建并行度；RED 时停掉最新启动的重任务。
- **质量把关**：三项质量门槛；验证按风险分 doc/code/high/e2e 四级，只有 high 级主会话才逐个复跑验收命令，归并后统一跑一次全量测试；高风险或大改动另派独立审核者。
- **可恢复**：所有状态写在台账里，上下文被压缩或会话重启后可以接着做。

## 自测
```bash
bash tests/test_resources.sh
python3 -m unittest discover tests
```
`resources.sh` 支持 `HQ_FAKE_CORES`、`HQ_FAKE_LOAD1`、`HQ_FAKE_MEM_TOTAL_MB` 等环境变量注入模拟读数，用来覆盖 GREEN/YELLOW/RED 各种情况。

## 已知限制
- 本地 CLI 能否直接创建云端子会话，取决于 CLI 版本（见 runtimes.md 的通道 D）。这类子会话监控能力较弱。需要强监控时，把主会话放在云端，再通过“连接电脑”处理本地任务。
- 进程内子代理和主会话共享同一台机器，资源保护只能控制派发节奏，没法限制子代理自己调用的进程。所以任务说明里的并行度限制很重要。
- 进程内子代理的返回结果只有 token 总数、分不出缓存读取，这类任务的 `tokens` 记为空，成本比较以云端子会话的 `cost_usd` 为主。
- 难度分档表是经验默认值，可以按你的账户和实际体验在 `skills/hq/calibration.md` 里调整；更推荐用 `/hq-retro` 按数据调整。
