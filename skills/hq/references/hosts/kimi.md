# 辅助执行者：Kimi（Moonshot）

## 1. 概述与核实状态

Kimi 在 hq 里**不是宿主**，而是**辅助执行者**：主宿主（运行 hq 的宿主，如 Claude Code、Codex）按 `calibration.md` 规则 10 把需求明确的 T0–T2 任务交给它，经 W 通道（`scripts/cli-worker.sh`）在独立 worktree 里执行，产出由主宿主审核。

核实状态（2026-11-25）：**只按公开资料整理，未实机运行。** 接口地址、模型名、计费口径都标“待核实”，首次使用后把实际值写进项目 `.hq/PLAYBOOK.md`，并在 CHANGELOG 里更新核实状态。

三条接入路径：

| 路径 | `--cli` | 做法 | 状态 |
|---|---|---|---|
| **一（推荐）：claude CLI 接 Kimi 的 Anthropic 兼容接口** | `claude` | `env_file` 里设 `ANTHROPIC_BASE_URL`、`ANTHROPIC_AUTH_TOKEN`，`--model` 填 Kimi 模型名 | claude 后端参数已核实；Kimi 端点待核实 |
| 二：OpenCode 的 Moonshot 提供方 | `opencode` | `--model <provider>/<model>`，密钥按 OpenCode 的提供方配置 | 未实机 |
| 三：原生 Kimi CLI | — | 暂无后端。需要先在装好的机器上看 `kimi --help`，确认非交互模式、JSON 输出、权限参数后，再按 `scripts/backends/README.md` 加 `backends/kimi.sh` 和假 CLI | 未做 |

路径一复用已核实的 `claude` 后端（沙箱映射、用量解析都现成），所以推荐它。

## 2. 能力（作为 W worker）

| 项 | 说明 |
|---|---|
| 隔离 | 独立 git worktree，分支 `hq/<id>`；和其他 W worker 一样占本地资源，派发前过 `resources.sh` |
| 回报 | 没有回信通道，结果写在交付格式里，主会话用 `cli-worker.sh status/usage` 读取 |
| 用量 | 路径一：`usage` 里的 `tokens` 可用；`cost_usd` 是 claude CLI 按 Claude 价格算的，**不可信**，task 记录填 null，`flags` 记 `billing:kimi`，以 Moonshot 控制台账单为准 |
| 记录 | `--label kimi`；task 记录 `assist: kimi`，model 写 `kimi:<模型名>` |

## 3. 档位映射（只到 T2）

辅助执行者最多承接 T2（规则 10）。具体模型名以 Moonshot 控制台当前列表为准（**待核实**），写进 PLAYBOOK `assist.profiles.kimi.models`：

| 档位 | 建议 | 思考深度 |
|---|---|---|
| T0 | 最快、最便宜的 Kimi 模型 | 不传 `--effort`（第三方接口是否支持待核实） |
| T1 | 主力 Kimi 模型 | 同上 |
| T2 | 主力或最强的 Kimi 模型 | 同上 |

## 4. 配置

### 本地

```bash
mkdir -p ~/.hq/env
cat > ~/.hq/env/kimi.env <<'EOF'
ANTHROPIC_BASE_URL=https://api.moonshot.cn/anthropic
ANTHROPIC_AUTH_TOKEN=<你的 Moonshot API Key>
EOF
chmod 600 ~/.hq/env/kimi.env
```

- 接口地址待核实：国内站一般是 `api.moonshot.cn`，国际站是 `api.moonshot.ai`，以官方文档为准。
- 不要在这个文件里设 `CLAUDE_CODE_SUBAGENT_MODEL` 之类会覆盖 `--model` 的变量。
- `cli-worker.sh` 只把它注入这一个 worker 进程，不影响主会话；权限不是 600 时拒绝启动（退出码 2）。

然后在 Claude Code 会话里一条命令配好（`--save` 对所有项目生效，换成 `--save-project` 只对当前项目生效）：

```
/hq --assist kimi --assist-cli claude --assist-env-file ~/.hq/env/kimi.env --assist-models T0=<模型>,T1=<模型>,T2=<模型> --save
/hq --assist codex,kimi --save        # 想让 codex 优先、kimi 兜底时再执行这一条
```

终端里等价的命令是 `python3 <hq 技能目录>/scripts/assist-config.py set --scope user --use kimi --profile kimi --cli claude --env-file ~/.hq/env/kimi.env --models T0=<模型>,T1=<模型>,T2=<模型>`。保存后用 `/hq --assist-show` 确认。写进文件的内容等同于下面这段（也可以手写进 `~/.hq/config.yaml` 或项目 PLAYBOOK 的授权区）：

```yaml
assist:
  use: [kimi]
  max_tier: T2
  profiles:
    kimi:
      cli: claude
      env_file: ~/.hq/env/kimi.env
      models: {T0: <模型>, T1: <模型>, T2: <模型>}
```

单次运行也可以不改配置：`/hq --assist kimi <目标>`（profile 仍从用户级配置或 PLAYBOOK 读）。思考深度不填时不传 `--effort`。

### 云端会话

云端容器里要满足三件事，缺一项时主会话把 kimi 从本次名单去掉，任务全部留给主宿主：
1. 容器里有 `claude` CLI（云端会话通常自带）。
2. 网络放行 Moonshot 接口主机，并把密钥作为环境的网络密钥保存（由代理注入，容器里看不到明文）；此时 `env_file` 只需写 `ANTHROPIC_BASE_URL`，`ANTHROPIC_AUTH_TOKEN` 填一个占位值。
3. `env_file` 不能提交进仓库；用环境的 setup script 生成，或在会话里临时创建。

## 5. 待核实

- Kimi Anthropic 兼容接口的确切地址、可用模型名、是否支持 `--effort` 和工具调用的全部格式。
- claude CLI 走第三方接口时 `result.usage` 是否完整。
- 原生 Kimi CLI 的非交互参数（路径三）。
