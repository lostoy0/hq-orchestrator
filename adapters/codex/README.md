# hq 的 Codex 适配模板

`agents/hq-t0.toml` … `hq-t4.toml` 是 5 个自定义 agent（由 `adapters/render.sh` 从 `adapters/tiers.tsv` 生成，不要手改：改 `tiers.tsv` 后运行 `adapters/render.sh --all`），对应 `skills/hq/calibration.md` 的 T0–T4 档位。每个文件有必填的 `name`、`description`、`developer_instructions`（按 hq 任务说明工作、按 STATUS/BRANCH/CHANGES/VERIFY/CHECKPOINTS/DERIVED/RISKS/QUESTIONS 交付），以及可选的 `model`、`model_reasoning_effort`。

> 已按官方文档核对（2026-11-25），未实机运行。要点：每个文件定义一个 agent；缺 `developer_instructions` 的文件据报会被忽略；`instructions`、`reasoning_effort` 这两个键名不生效；只设 `model` 不设 effort 时沿用之前解析出的 effort；`sandbox_mode`、`approval_policy`、`model_provider`、`mcp_servers` 写在 agent 文件里**不会**覆盖父会话的配置，所以模板里不写。

## 安装

- 个人使用：复制到 `~/.codex/agents/`。
- 仅某个仓库：复制到仓库的 `.codex/agents/`。
- 也可以用仓库根目录的 `./install.sh --host codex --with-agents [--scope project --project-dir <项目>]`（旧写法 `--with-codex-agents`），按范围自动放到上面两处之一。
- 安装时直接填模型（推荐）：加 `--model-map 'T0=<模型>,T1=<模型>,T2=<模型>,T3=<模型>,T4=<模型>'`，会现场生成带真实模型名的模板，不用再手改占位符；没填的档位仍是占位符。
- 本机装了 codex 时可以写 `--model-map auto`：读 `codex debug models` 的模型目录，按模型说明（小而便宜 / 日常主力 / 最强）推荐 T0–T4，安装时打印推荐结果。先看推荐可运行 `python3 skills/hq/scripts/assist-config.py suggest`。
- hq 技能本身另行复制到 `~/.agents/skills/` 或仓库 `.agents/skills/`（install.sh 会做）。

## 替换占位符

文件里的 `model = "<...>"` 是占位符，**必须替换**，否则无法使用。
1. 运行 `python3 skills/hq/scripts/assist-config.py models` 看你账户当前可用的模型和各自支持的思考深度（读 `codex debug models`，以 codex 自己的模型列表为准，不要凭记忆填）。
2. 按注释里的档次挑选：T0 最快的小模型；T1 快速的中档；T2 中档；T3、T4 最强模型。
3. 把名字写进各文件的 `model`，`model_reasoning_effort` 按需调整（low / medium / high）。
4. 首次运行 hq 时，把最终映射写进 PLAYBOOK。

不设置 `model` 时子代理继承父会话的模型，也可以删掉这一行。
