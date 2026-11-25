# 项目经验手册（PLAYBOOK）

实际使用时放在项目的 `.hq/PLAYBOOK.md`。`/hq` 开始前读它；`/hq-retro` 复盘后更新它。
只写与**本项目**有关的内容。涉及插件本身的改进，走 `/hq-retro` 的插件建议，不要写在这里。

## 授权

用户在这里一次性设定，`/hq` 按此执行，不再逐次询问。没写的项取默认值。

```yaml
merge_default: ask        # ask | auto-if-gates-pass：合入默认分支。默认 ask；auto-if-gates-pass 仅在三项质量门槛都通过时自动合入
open_pr: ask              # ask | auto：开 PR。默认 ask
budget_usd: <数额>        # 本项目单次运行的预算上限（美元）。超出前必须停下来问用户
autonomy: auto            # auto | confirm-plan：默认 auto；confirm-plan 表示派发前计划必须经用户确认
worker_clis: []           # 跨厂商 worker（W 通道）可用的 CLI，可选 codex、claude、opencode、gemini、cursor。默认空，即关闭；宿主自己的 CLI 不需要列
runs_persist: off         # off | branch | commit：运行记录是否保存进仓库。branch 写进专用分支 hq/runs（推荐，云端必开）；commit 随本批改动提交；本地默认 off，云端没写时 /hq 问一次
share_hint: pending       # pending | shown：/hq-retro 是否已提示过“可导出脱敏数据帮助改进插件”。只提示一次
assist:                   # 辅助执行者（calibration.md 规则 10），默认关闭。/hq --assist … 可在单次运行覆盖
  use: []                 # 按优先顺序，如 [codex, kimi]；空表示关闭
  max_tier: T2            # 辅助最多承接到哪一档，只能是 T0、T1 或 T2
  profiles:               # 每个辅助执行者一项；模型名填你账户里实际可用的
    codex:
      cli: codex          # W 通道用哪个 CLI：codex | claude | opencode | gemini | cursor
      models: {T0: <模型>, T1: <模型>, T2: <模型>}
      effort: {T0: low, T1: low, T2: medium}
    kimi:
      cli: claude         # 经 claude CLI 接 Kimi 的 Anthropic 兼容接口，见 references/hosts/kimi.md
      env_file: ~/.hq/env/kimi.env   # 只写路径；文件里放 ANTHROPIC_BASE_URL、ANTHROPIC_AUTH_TOKEN，chmod 600
      models: {T0: <模型>, T1: <模型>, T2: <模型>}
cost_weight:              # 按计费方的额度成本，影响 calibration.md 规则 9（拿不准时都上调一步：low 上调一整档，high 默认只上调思考深度一级）。默认如下
  claude-code: high
  codex: low
  dsh: low
  deepseek-backend: low
```

## 项目事实

- 测试命令：`<命令>`
- 构建命令：`<命令>`
- lint 命令：`<命令>`
- 验证需要的环境：`<依赖的服务、数据、环境变量名（不写值）、系统>`
- 必须在本地执行的部分：`<比如需要 VPN、本机登录态、GPU、模拟器的步骤；没有就写“无”>`
- 其他：`<目录约定、不能动的文件、分支规则>`

## 经验

最多 30 条。满了就用新的替换最旧或证据最弱的，不要追加到 31 条。
每条都要有证据，没有证据的不写。

| # | 内容 | 证据（run/task） | 日期 |
|---|------|------------------|------|
| 1 | `<一句话，可执行。例：集成测试要先起 docker compose，否则超时>` | `<run-id / t3>` | `<YYYY-MM-DD>` |

## 选档偏好

本项目里某类任务适合的档位，及依据。`/hq` 选档时优先参考这里，其次才是 `calibration.md`。
降档只能写已经通过小范围实验验证的内容。
**按宿主分别记录**：同一档位在不同宿主上对应的模型不同，每行写明宿主。首次在新宿主上运行时，`/hq` 把实际用的档位映射（T0–T4 → 模型/深度）写在下方“宿主映射”表。

| 宿主 | 任务类型 | 档位 | 依据（run/task、一次通过率等） | 日期 |
|------|----------|------|--------------------------------|------|
| `<claude-code>` | `<例：给已有函数补单元测试>` | `<T1>` | `<run-id: 5 个任务一次通过 5 个，返工 0>` | `<YYYY-MM-DD>` |

### 宿主映射

| 宿主 | T0 | T1 | T2 | T3 | T4 | 依据 / 日期 |
|------|----|----|----|----|----|-------------|
| `<codex>` | `<模型/深度>` | | | | | `<首次运行 run-id>` |
