# 参与贡献 / Contributing

中文 | [English](#english)

感谢你愿意改进 hq-orchestrator。

## 许可与贡献条款

本项目以 [Apache-2.0 加 Commons Clause](LICENSE) 授权，作者保留自行出售（含市场上架、收费支持）的权利。因此提交贡献（PR、补丁）即表示你同意：

1. 你的贡献按同一许可（Apache-2.0 加 Commons Clause）授权；
2. 你授予作者永久、不可撤销、可转授权的权利，可以在作者出售或收费提供的版本中包含你的贡献，包括以其他条款提供；
3. 你有权提交这些内容（是你自己写的，或来源的许可允许这样用）。

不同意请不要提交 PR。有疑问先开 issue 问。

## 提交前

- 改动要小而聚焦，一个 PR 一件事；分支名沿用 `feat/…`、`fix/…`。
- 跑自测，全部通过再提交：
  ```bash
  for t in tests/test_*.sh; do bash "$t" || echo "FAILED: $t"; done
  python3 -m unittest discover tests
  ```
- 改了行为（技能、脚本、校准表），在 `CHANGELOG.md` 加一条，按文件顶部的五项格式写：改动、原因/假设、验收指标、状态、复盘报告。新改动状态一律先写“待验证”。
- 改了 `adapters/tiers.tsv`，用 `adapters/render.sh` 重新生成各宿主的 `hq-t0…t4` 模板，不要手改生成物。
- 中英文 README 要同步改。
- 版本号只在发版时改（`.claude-plugin/plugin.json`、`.claude-plugin/marketplace.json`、`gemini-extension.json` 保持一致），普通 PR 不用动。
- 没有在真实宿主上跑过的适配，请在文档里明确写“未实机运行”，不要写成已验证。

## 分享运行数据

欢迎用 `/hq-retro --export` 导出脱敏数据，按 [issue 模板](.github/ISSUE_TEMPLATE/retro-data.md) 分享。issue 是公开的，贴之前请再检查一遍。

<a id="english"></a>

## English

Thanks for helping improve hq-orchestrator.

**License and contribution terms.** The project is licensed under [Apache-2.0 with the Commons Clause](LICENSE), and the author reserves the right to sell it (including marketplace listings and paid support). By submitting a contribution (PR or patch) you agree that:

1. your contribution is licensed under the same license (Apache-2.0 with the Commons Clause);
2. you grant the author a perpetual, irrevocable, sublicensable right to include your contribution in versions the author sells or offers for a fee, including under other terms;
3. you have the right to submit it (you wrote it, or its source's license allows it).

If you don't agree, please don't open a PR. Open an issue first if you have questions.

**Before you submit**

- Keep changes small and focused, one thing per PR; branch names follow `feat/…` and `fix/…`.
- Run the self-tests and make sure they all pass:
  ```bash
  for t in tests/test_*.sh; do bash "$t" || echo "FAILED: $t"; done
  python3 -m unittest discover tests
  ```
- If you change behavior (skills, scripts, the calibration table), add a `CHANGELOG.md` entry in the five-field format at the top of that file: change, reason/hypothesis, acceptance metric, status, retro report. New changes start as "待验证" (unverified).
- If you change `adapters/tiers.tsv`, regenerate the `hq-t0…t4` templates with `adapters/render.sh`; don't hand-edit generated files.
- Keep `README.md` and `README.en.md` in sync.
- Version numbers change only at release time (keep `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` and `gemini-extension.json` identical); ordinary PRs leave them alone.
- If an adapter hasn't been run on a real host, say "not run on a real host" in the docs. Don't present it as verified.

**Sharing run data.** Export anonymized data with `/hq-retro --export` and share it with the [issue template](.github/ISSUE_TEMPLATE/retro-data.md). Issues are public, so review the content once more before posting.
