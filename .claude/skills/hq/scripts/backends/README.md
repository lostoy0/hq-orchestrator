# cli-worker.sh 的 CLI 后端

每个文件 `<cli>.sh` 对应 `cli-worker.sh start --cli <cli>`，由 cli-worker.sh `source` 进来，必须定义：

| 名称 | 作用 |
|---|---|
| `be_argv` | 读 `MODEL`、`EFFORT`、`SANDBOX`、`BRIEF`、`ID`，填数组 `argv`（要执行的命令）；设 `STDIN_SRC=brief`（简报经 stdin 传入）或 `null`；不支持的选项把说明追加到 `NOTES`（写进 `.hq/workers/<id>/notes`） |
| `be_usage <out.jsonl>` | 输出一行 JSON：`{"tokens":…,"cost_usd":…,"source":…}`；口径：tokens = input + output + cache_write，不含 cache_read；拿不到填 null |

约定：
- sandbox 只有 `read-only`、`workspace-write`、`danger-full-access` 三档；`danger-full-access` 的 `--allow-dangerous` 闸门在 cli-worker.sh 里统一检查。CLI 没有对应档位时选**更保守**的映射，并在 `NOTES` 里写明；实在映射不了就 `return 2`（cli-worker.sh 以退出码 2 拒绝，不建 worktree）。
- 参数来源和核实状态写在文件头注释里；新增后端要在 `tests/fixtures/fake-cli/` 加假 CLI，并在 `tests/test_cli_worker.sh` 覆盖参数拼装和用量解析。
