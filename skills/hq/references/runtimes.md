# 派发通道总览与宿主索引

`SKILL.md` 里只出现抽象能力和通道字母。每种宿主的具体调用方式见对应宿主文档：

| 宿主 | 文档 | 识别特征 |
|---|---|---|
| Claude Code（含云端会话） | `hosts/claude-code.md` | 有 Agent 工具，或有 `mcp__claude-code-remote__*` 工具 |
| Claude Code 接 DeepSeek 后端 | `hosts/deepseek.md` | 同上，且 `ANTHROPIC_BASE_URL` 指向 deepseek |
| DeepSeek Harness（dsh，DeepSeek 推荐路径） | `hosts/dsh.md` | 有 `subagent`、`list_subagent_models`、`list_agents` 工具，或存在 `~/.dsh/`、`$DSH_HOME` |
| Codex（含接 DeepSeek 后端） | `hosts/codex.md`（DeepSeek 部分另见 `hosts/deepseek.md`） | 能看到 `~/.codex/`，能用 codex 的子代理功能 |
| OpenCode、Cursor、Gemini CLI 及其他支持 SKILL.md 的工具 | `hosts/generic.md` | 见该文档识别表；有 shell 用 W，否则降级模式 |

## 抽象能力

| 能力 | 含义 |
|---|---|
| spawn_worker | 派出一个带完整说明的 worker，可指定模型、思考深度、隔离方式（worktree / 独立容器） |
| monitor | 查看 worker 状态和交付结果 |
| message_worker | 主会话与 worker 双向发消息（纠偏、回答提问、接收 CHECKPOINT） |
| stop_worker | 中断或停止 worker |
| worker_usage | 读取 worker 用量：`cost_usd` 优先；tokens = input + output + cache_write，不含 cache_read；拿不到填 null |
| schedule_checkin | 定时唤醒主会话做兜底巡检 |
| remote_workers | 在云端独立环境运行 worker |
| local_machine | 在用户电脑上执行（主会话在云端时） |
| concurrency_limit | 同时运行 worker 的上限 |

## 通道（通用规则）

### A：进程内子代理
- 和主会话同一台机器，构建和测试会争用 CPU 和内存，派发前必须过一遍 `resources.sh`。
- 改代码的任务必须用 worktree 隔离；不是 git 仓库时写操作只能串行。worktree 临时目录要先确认被 git 忽略。
- 通常没有回信通道：遇到检查点就提前返回，主会话处理后再派新的接着做。

### B：云端子会话
- 每个子会话有独立容器，不占本地资源，但消耗额度；并发不超过预算上限。
- 只能看到已推送的代码。派发前确认基线已推送；还没推送时推到 `hq/*` 分支（如 `hq/base`）作基线（默认自动，推其他分支需要授权）。
- 正常完成不一定通知：说明里要求按 message_worker 回报，主会话用 schedule_checkin 设兜底巡检。
- 不要让子会话进入需要人工批准计划的模式，否则没人批准会一直卡住。

### C：用户电脑（主会话在云端时）
- 只能连在线的电脑；连接需要用户批准；一次只连一台电脑的一个文件夹。
- 资源检测也要在那台电脑上跑。worker 无法在那台电脑上执行时，由主会话亲自执行这些本地步骤（同样控制规模）。

### D：从本地 CLI 发起云端任务
- 先确认 CLI 支持再用。主会话很难自动监控，只能等分支推送后 `git fetch` 审核。需要强监控时，把整个编排放到云端会话做（B + C）。

### W：CLI 子进程 worker
- 由 `scripts/cli-worker.sh` 在独立 git worktree 里后台运行 `codex exec` 或 `claude -p`。任何有 shell 的宿主都能用。
- 接口：`start --id <id> --cli codex|claude --model <m> [--effort <e>] --brief <说明文件> [--base <分支>] [--sandbox read-only|workspace-write|danger-full-access] [--allow-dangerous]`；`status --id <id>`、`stop --id <id>`、`usage --id <id>`（输出 JSON）、`list`。状态写在 `.hq/workers/<id>/`。
- sandbox 默认 `workspace-write`（claude 映射为 `--permission-mode acceptEdits`，read-only 映射为 `plan`）。`danger-full-access`（codex 原样传入；claude 映射为 `--dangerously-skip-permissions`）关闭全部防护，必须同时传 `--allow-dangerous`，否则拒绝并以退出码 2 退出；只有用户明确授权才这样用。
- **何时用**：宿主没有合适的子代理能力；需要真正的进程隔离；用户在 PLAYBOOK 授权区开启了跨厂商 worker（`worker_clis: [codex, claude]`，默认关闭）。
- 占本地资源，派发前过 `resources.sh`，按 A 的规则计槽位。
- 没有回信通道：说明里不写宿主专有回报方式，结果写在交付格式里，主会话用 `status` / `usage` 读取。
- 用到非宿主自带的模型时，task 记录的 model 写成 `<cli>:<模型名>`。

### 降级模式（channel 记 `main`）
- 宿主没有子代理能力、也没有 shell 可用 W 时，主会话按同样的计划、台账、质量门槛**串行**亲自执行，仍然记录 task 数据。

## 建议用户手动调档

主会话改不了运行中 worker 的模型和思考深度。只有换会话交接代价太高（上下文很重、即将完成）、worker 又确实卡住时，才一次性给出明确建议：打开哪个会话、切到什么模型和深度、切好后怎么回复；不方便切换就改为升档新开 worker 交接。具体话术见宿主文档（如 `hosts/claude-code.md`）。记录：task 的 `user_manual_adjust` 记为 true，并写进台账“调档、交接与衍生任务”区。

## 位置与通道速查

| 主会话位置 \ 任务需求 | 普通任务 | 需要本地资源的任务 |
|---|---|---|
| 云端 | B（首选）或 A（小任务）；跨厂商用 W | C |
| 本地 | A（受资源限制）或 W；大任务可考虑 D | A 或 W |
| 无子代理能力 | W；没有 shell 就降级模式 | 主会话亲自做 |
