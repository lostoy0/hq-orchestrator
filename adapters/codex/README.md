# hq 的 Codex 适配模板

`agents/hq-t0.toml` … `hq-t4.toml` 是 5 个自定义 agent，对应 `skills/hq/calibration.md` 的 T0–T4 档位。每个文件有必填的 `name`、`description`、`developer_instructions`（按 hq 任务说明工作、按 STATUS/BRANCH/CHANGES/VERIFY/CHECKPOINTS/DERIVED/RISKS/QUESTIONS 交付），以及可选的 `model`、`model_reasoning_effort`。

> 已按官方文档核对（2026-11-25），未实机运行。要点：每个文件定义一个 agent；缺 `developer_instructions` 的文件据报会被忽略；`instructions`、`reasoning_effort` 这两个键名不生效；只设 `model` 不设 effort 时沿用之前解析出的 effort；`sandbox_mode`、`approval_policy`、`model_provider`、`mcp_servers` 写在 agent 文件里**不会**覆盖父会话的配置，所以模板里不写。

## 安装

- 个人使用：复制到 `~/.codex/agents/`。
- 仅某个仓库：复制到仓库的 `.codex/agents/`。
- 也可以用仓库根目录的 `./install.sh --host codex --with-codex-agents [--scope project --project-dir <项目>]`，按范围自动放到上面两处之一。
- hq 技能本身另行复制到 `~/.agents/skills/` 或仓库 `.agents/skills/`（install.sh 会做）。

## 替换占位符

文件里的 `model = "<...>"` 是占位符，**必须替换**，否则无法使用。
1. 运行 `codex` 看你账户当前可用的模型（以 codex 自己的模型列表为准，不要凭记忆填）。
2. 按注释里的档次挑选：T0 最快的小模型；T1 快速的中档；T2 中档；T3、T4 最强模型。
3. 把名字写进各文件的 `model`，`model_reasoning_effort` 按需调整（low / medium / high）。
4. 首次运行 hq 时，把最终映射写进 PLAYBOOK。

不设置 `model` 时子代理继承父会话的模型，也可以删掉这一行。
