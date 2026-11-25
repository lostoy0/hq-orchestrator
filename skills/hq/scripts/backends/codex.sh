# codex 后端：codex exec。参数 --json、"-"（stdin）已按官方文档核对；-m、-c、-s 待 `codex exec --help` 核对。
be_argv() {
  # 简报经 stdin 传入（codex exec 的 PROMPT 为 "-" 时读 stdin），避免超长命令行
  argv=(codex exec -m "$MODEL")
  [ -n "$EFFORT" ] && argv+=(-c "model_reasoning_effort=$EFFORT")
  argv+=(-s "$SANDBOX" --json -)
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
