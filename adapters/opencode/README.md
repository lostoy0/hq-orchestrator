# hq 的 OpenCode 适配模板

`agents/hq-t0.md` … `hq-t4.md` 是 5 个 OpenCode V2 子代理（`mode: subagent`），对应 `skills/hq/calibration.md` 的 T0–T4 档位。它们由 `adapters/render.sh` 从 `adapters/tiers.tsv` 生成，**不要手改**：改 `tiers.tsv` 后运行 `adapters/render.sh --all`。

> 依据 OpenCode V2 官方文档（2026-11-25），未实机运行。要点：Markdown agent 放在 `~/.config/opencode/agents/`（个人）或 `<项目>/.opencode/agents/`（项目），文件名就是 agent ID；frontmatter 用 `description`、`mode`、`model`（`provider/model#variant`），正文是系统提示；不要用 V1 字段（`tools`、`permission`、`temperature`、`maxSteps` 等）。子代理不设 model 时继承父会话模型。

## 安装

```bash
./install.sh --host opencode --with-agents \
  --model-map 'T0=<provider/小模型>,T1=<provider/中档>,T2=<provider/中档>,T3=<provider/最强>,T4=<provider/最强>'
```

- 每个值写 `provider/model`，安装时按档位自动追加 `#low`/`#medium`/`#high`；模型没有这些 variant 时，直接写 `provider/model#<variant>`。
- 用 `opencode models` 查看可用模型，不要凭记忆填。
- 不带 `--model-map` 时装的是不含 model 的模板：子代理继承父会话模型，档位不生效（hq 会在 notes 记 `tier:not-applied`）。之后可以加 `--force` 带上映射重装。
- `--scope project --project-dir <项目>` 装到项目的 `.opencode/agents/`。

## 权限

模板不写 `permissions`，子代理沿用全局权限。若全局 `edit`/`shell` 需要审批，后台子代理会频繁请求批准；需要时在你的 OpenCode 配置里为 `hq-t*` 单独设置（安装脚本不改配置），例如：

```jsonc
{
  "agents": {
    "hq-t2": {
      "permissions": [
        { "action": "edit", "resource": "*", "effect": "allow" },
        { "action": "shell", "resource": "*", "effect": "ask" }
      ]
    }
  }
}
```

具体用法和隔离注意事项见 `skills/hq/references/hosts/opencode.md`。
