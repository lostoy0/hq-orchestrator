# 安全策略 / Security Policy

中文 | [English](#english)

## 报告漏洞

请**不要**在公开 issue 里披露安全问题。请在仓库的 **Security** 页签点 **Report a vulnerability**，用 GitHub 私密漏洞报告提交。请写清影响范围、复现步骤和你测试的版本。

## 重点关注的范围

本项目的脚本会在你的机器上启动其他 AI 编程命令行，所以下面这些尤其重要：

- `skills/hq/scripts/cli-worker.sh` 和 `backends/*.sh`：拼接命令行参数、选择沙箱和权限模式、在 git worktree 里运行 worker。关注命令注入、沙箱或权限被意外放宽。
- `install.sh`：复制文件、`--update` 和 `--uninstall` 会删改目录。关注越界写入、误删。
- `skills/hq/scripts/metrics.py --export-anon`：脱敏导出。关注白名单之外的字段泄露（路径、仓库名、提示词内容等）。
- `skills/hq/scripts/runs-persist.sh`：把运行记录写进 git 分支。

## 不算漏洞的情况

- 你主动关闭沙箱或授予 worker 更高权限后发生的事（`PLAYBOOK.md` 里的授权配置是你自己设的）。
- 第三方 CLI（Claude Code、Codex、OpenCode、Gemini CLI、Cursor 等）本身的问题，请报给对应厂商。

## 支持的版本

只维护最新发布的版本。

<a id="english"></a>

## English

**Reporting.** Please do **not** disclose security issues in public issues. Use the **Security** tab of this repository and click **Report a vulnerability** (GitHub private vulnerability reporting). Include the impact, steps to reproduce and the version you tested.

**Areas of particular interest.** The scripts launch other AI coding CLIs on your machine, so these matter most:

- `skills/hq/scripts/cli-worker.sh` and `backends/*.sh`: build command lines, choose sandbox and permission modes, and run workers in git worktrees. Look for command injection or an unintentionally weakened sandbox or permissions.
- `install.sh`: copies files; `--update` and `--uninstall` modify or delete directories. Look for writes outside the intended directories and accidental deletion.
- `skills/hq/scripts/metrics.py --export-anon`: anonymized export. Look for fields outside the allowlist leaking (paths, repository names, prompt content).
- `skills/hq/scripts/runs-persist.sh`: writes run records into a git branch.

**Out of scope.** Behavior after you deliberately disable a sandbox or grant workers broader permissions (the authorization settings in `PLAYBOOK.md` are yours to set), and bugs in third-party CLIs themselves; report those to their vendors.

**Supported versions.** Only the latest release is maintained.
