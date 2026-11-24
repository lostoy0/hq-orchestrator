# hq-orchestrator：司令部模式

中文 | [English](README.en.md)

在普通会话里（本地 CLI 或云端会话都可以）实现类似 Projects 的工作方式：主会话负责统筹，子会话负责执行。

## 包含什么
```
.claude-plugin/plugin.json        plugin 清单
.claude-plugin/marketplace.json   方便用 /plugin marketplace add 安装
skills/hq/SKILL.md                核心流程：侦察 → 规划 → 选模型 → 选位置 → 控并发 → 派发 → 监控 → 审核归并 → 汇报
skills/hq/references/runtimes.md  各派发通道的具体用法
skills/hq/references/brief-template.md  子会话任务说明模板与交付格式
skills/hq/scripts/resources.sh    资源探测（Linux/cgroup/macOS），输出还能新开几个本地任务
PROMPT.md                         不装 plugin 时直接粘贴用的精简提示词
```

## 安装

**方式 1：个人 skill（本地最简单）**
```bash
mkdir -p ~/.claude/skills && cp -r skills/hq ~/.claude/skills/hq
```
装好后在任意项目里输入 `/hq <目标>` 即可使用。

**方式 2：作为 plugin 安装**（先把本目录推到你自己的 GitHub 仓库，或者放在本地某个路径下）
```
/plugin marketplace add <本地路径 或 owner/repo>
/plugin install hq-orchestrator@hq-orchestrator-marketplace
```
装好后用 `/hq-orchestrator:hq <目标>` 调用。

**方式 3：在云端会话中使用**
云端容器里没有你本机的 `~/.claude`，所以要把 skill 放进项目仓库：
```bash
mkdir -p .claude/skills && cp -r <本目录>/skills/hq .claude/skills/hq && git add .claude/skills/hq
```
提交后，基于这个仓库新开的云端会话都能用 `/hq`。也可以在云端会话里用方式 2 的 marketplace 安装。

## 自测
修改 `resources.sh` 后运行：
```bash
bash tests/test_resources.sh
```
脚本支持 `HQ_FAKE_CORES`、`HQ_FAKE_LOAD1`、`HQ_FAKE_MEM_TOTAL_MB` 等环境变量注入模拟读数，用来覆盖 GREEN/YELLOW/RED 各种情况。

## 使用示例
```
/hq 给 api 服务加上导出 CSV 功能，并补齐测试和文档；前端改动要在我本机跑 e2e
```
主会话会先给出计划（任务表、各任务的模型和思考深度、运行位置、并发数），你确认后才开始派发。进度可以随时问，也可以直接查看 `.hq/LEDGER.md`。

## 设计要点
- **难度分档**：5 个维度打分，分成 T0 到 T4 五档，对应 haiku/low 到 opus/high。失败后先改任务说明，再考虑升档。
- **运行位置路由**：需要本地资源的任务一定在本地跑，能并行的长任务放到云端，小任务在进程内执行。
- **资源保护**：每次派发前都检测资源，按 GREEN/YELLOW/RED 三级控制派发；给子会话限定构建并行度；RED 时停掉最新启动的重任务。
- **质量把关**：说明必须完整，交付必须带验证输出，主会话亲自复跑验收命令，高风险改动另派独立审核者。
- **可恢复**：所有状态写在台账里，上下文被压缩或会话重启后可以接着做。

## 已知限制
- 本地 CLI 能否直接创建云端子会话，取决于 CLI 版本（见 runtimes.md 的通道 D）。这类子会话监控能力较弱。需要强监控时，把主会话放在云端，再通过“连接电脑”处理本地任务。
- 进程内子代理和主会话共享同一台机器，资源保护只能控制派发节奏，没法限制子代理自己调用的进程。所以任务说明里的并行度限制很重要。
- 难度分档表是经验默认值，可以按你的账户和实际体验在 SKILL.md 第 2 步里调整。
