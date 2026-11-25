# codex 后端：codex exec。已实机核实（codex-cli 0.172.0，macOS 26.6.2，2026-11-25）：-m、-c model_reasoning_effort=、
# -s read-only/workspace-write（danger-full-access 只在 --help 里核对，未实跑）、--json、"-"（stdin）均被接受；生效的 model/effort 见 ~/.codex/sessions 的 turn_context；turn.completed.usage 字段与下方解析一致。
be_argv() {
  # 简报经 stdin 传入（codex exec 的 PROMPT 为 "-" 时读 stdin），避免超长命令行
  argv=(codex exec -m "$MODEL")
  [ -n "$EFFORT" ] && argv+=(-c "model_reasoning_effort=$EFFORT")
  argv+=(-s "$SANDBOX" --json -)
  if [ "$SANDBOX" = workspace-write ]; then
    # 实测：workspace-write 沙箱把 .git 当受保护路径（worktree 的 git 目录在主仓库 .git/worktrees/<id>），
    # git add 建不了 index.lock；--add-dir 主仓库 .git 也无效。改由 cli-worker 在沙箱外代提交。
    BE_COMMIT=1
    NOTES="${NOTES}codex 沙箱不能写 .git，worker 无法自行提交：退出码 0 时由 cli-worker 在沙箱外把 worktree 改动提交到 hq/<id>；"
  fi
  STDIN_SRC=brief
}
be_usage() {
  python3 - "$1" <<'PY'
import sys,json
def n(x): return x if isinstance(x,(int,float)) and not isinstance(x,bool) else None
tokens=None; cost=None; source=None
for line in open(sys.argv[1],encoding="utf-8",errors="replace"):
    try: o=json.loads(line)
    except Exception: continue
    if not isinstance(o,dict): continue
    u=o.get("usage")
    if not isinstance(u,dict) and isinstance(o.get("msg"),dict): u=o["msg"].get("usage") or o["msg"].get("info")
    if isinstance(u,dict):
        # turn.completed.usage：input_tokens 已含 cached_input_tokens（cache_read），按口径扣除；
        # output_tokens 已含 reasoning_output_tokens，不再相加；无 cache_write 概念。
        # usage 是整个线程的累计值：单次 exec 取最后一条即可；恢复会话（exec resume）时需与上次的值做差。
        i=n(u.get("input_tokens")); out=n(u.get("output_tokens")); cr=n(u.get("cached_input_tokens")) or 0
        if i is not None or out is not None:
            tokens=int(max((i or 0)-cr,0)+(out or 0)); source="codex:usage"
        c=n(u.get("cost_usd"))
        if c is not None: cost=c
print(json.dumps({"tokens":tokens,"cost_usd":cost,"source":source}))
PY
}
