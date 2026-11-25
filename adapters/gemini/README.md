# hq 的 Gemini CLI 适配

## 两种安装方式（二选一）

**方式 A：Gemini 扩展（推荐给只用 Gemini CLI 的人）**
```bash
gemini extensions install https://github.com/lostoy0/hq-orchestrator --ref v0.4.5
```
仓库根目录的 `gemini-extension.json` 让整个仓库成为一个扩展：提供 `skills/hq`、`skills/hq-retro` 两个技能和 `commands/hq.toml`、`commands/hq-retro.toml` 两个命令（`/hq <目标>`、`/hq-retro`）。更新用 `gemini extensions update hq-orchestrator`，卸载用 `gemini extensions uninstall hq-orchestrator`。扩展**不带**子代理模板（见下），装完后可再单独装模板。

**方式 B：install.sh**
```bash
./install.sh --host gemini --with-agents --model-map 'T0=<小模型>,T1=<快速中档>,T2=<中档>,T3=<最强>,T4=<最强>'
```
技能装到 `~/.gemini/skills`（与其他工具一起装时为共用的 `~/.agents/skills`），子代理装到 `~/.gemini/agents/hq-t*.md`。这种方式没有 `/hq` 命令，在会话里说“用 hq 技能 + 目标”即可。

两种都装时，Gemini CLI 里用户目录的技能优先于扩展里的同名技能（官方文档的发现顺序），不会冲突，但建议只留一种。

## 子代理模板

`agents/hq-t0.md` … `hq-t4.md` 由 `adapters/render.sh` 从 `adapters/tiers.tsv` 生成，**不要手改**。格式依据 Gemini CLI 官方文档 `docs/core/subagents.md`（2026-11-24），未实机运行：
- frontmatter 必填 `name`（就是主会话调用它时的工具名）、`description`；可选 `kind: local`、`model`、`max_turns`（默认 30，模板设 100）、`timeout_mins`（默认 10，模板设 60）；不写 `tools` 时继承主会话的全部工具。
- **没有思考深度设置**：T0/T1、T3/T4 只能靠模型区分；需要时给 T1 选比 T0 强一点的模型。
- 不带 `--model-map` 时不写 `model`，子代理继承主会话模型，档位不生效。也可以不重装，改在 `~/.gemini/settings.json` 里覆盖：
  ```json
  { "agents": { "overrides": { "hq-t0": { "modelConfig": { "model": "<小模型>" } } } } }
  ```

**为什么扩展里不带子代理**：扩展的子代理要放在仓库根目录的 `agents/`，而同一个仓库也是 Claude Code 插件，Claude Code 会把根目录 `agents/` 当成自己的子代理加载，出现 5 个多余的 `hq-t*`。所以模板放在 `adapters/gemini/agents/`，由 install.sh 安装。
