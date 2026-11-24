# 派发通道用法

## A：进程内子代理（`Agent` 工具）

```
Agent(
  description="t3 实现导出接口",
  subagent_type="general-purpose",     # 只读调研用 "Explore"
  model="sonnet",                      # haiku | sonnet | opus
  effort="medium",                     # 本 skill 明确要求按档位设置
  isolation="worktree",                # 改代码的任务必须加；只读任务不加
  run_in_background=True,
  prompt=<完整任务说明>
)
```
- 完成后会自动通知，不要轮询。中途需要补充信息时，用 `SendMessage` 发给它的 id。
- 停止任务用 `TaskStop`；查看正在运行的任务用 `TaskList`。
- 子代理和主会话在同一台机器上，构建和测试会争用 CPU 和内存，派发前必须过一遍 `resources.sh`。
- worktree 只有在仓库是 git 仓库时才能用；不是 git 仓库时，只能串行做写操作。

## B：云端子会话（`mcp__claude-code-remote__*`，在云端会话中可用）

创建：
```
create_session(
  title="hq/t3 导出接口",
  prompt=<完整任务说明，并在里面写上主会话的 session_id，方便子会话回报>,
  source_url="https://github.com/<owner>/<repo>",
  source_revision="<基线分支>",
  outcome_branch="hq/t3",
  model="sonnet",
  effort="medium",
  tags=["hq:<项目名>"]
  # 不要传 permission_mode="plan"，否则没人批准时会一直卡住
)
```
- 查看自己的 session_id：调用 `get_session()`，不带参数。
- 巡检：`list_sessions(children=true)` 先看全局，再对需要细看的任务用 `get_session(id)` 看 `status_bucket`（working / blocked / review_ready / completed / failed）。
- 看结果：`list_events(session_id, kinds=["result","assistant"], limit=100)`。
- 纠偏：`send_message(session_id, ...)`，或者 `interrupt_session`；完成后用 `archive_session`。
- 巡检提醒：`send_later(delay_minutes=15, message="HQ 巡检：读取 .hq/LEDGER.md，检查 RUNNING 任务")`。任务全部完成后，用 `delete_trigger` 取消还没触发的提醒。
- 子会话默认继承主会话的云环境。需要别的网络或密钥时，用 `list_environments` 查到对应环境，再传 `environment_id`。
- 子会话只能看到已推送的代码。派发前确认基线已推送；如果还没推送，推送需要用户同意。

## C：用户电脑（主会话在云端时）

1. `list_computer_folders`：只能选 `online:true` 的文件夹。
2. `request_computer_folder(environment_id, computer_name, folder)`：用户需要批准。
3. 连上之后，Bash、Read、Edit 等工具调用加 `_host:"<电脑名>"`。派给子代理的说明里也要写明这一点。如果子代理无法使用 `_host`，就由主会话亲自执行这些本地步骤（同样要控制规模）。
4. 资源检测也要在那台电脑上跑：`Bash(_host=..., command="bash <路径>/resources.sh 1500 1")`。脚本需要先拷到那台电脑上，或者直接内联执行。
5. 一个会话同一时间只能连一台电脑的一个文件夹。

## D：从本地 CLI 发起云端任务

- 先看 `claude --help` 里有没有创建云端会话的参数（不同版本叫法可能不同，例如 `--remote` 或 `--cloud`），用 Bash 发起。
- 这类任务主会话很难自动监控，只能请用户在 claude.ai/code 里查看，或者等它推送分支后再 `git fetch` 审核。
- 如果用户需要强监控，建议把整个编排放到云端会话里做：主会话在云端，用 B 通道派远程任务，用 C 通道处理本地任务。

## 位置与通道速查

| 主会话位置 \ 任务需求 | 普通任务 | 需要本地资源的任务 |
|---|---|---|
| 云端 | B（首选，各自独立容器）或 A（小任务） | C |
| 本地 | A（受资源限制），大任务可考虑 D | A |
