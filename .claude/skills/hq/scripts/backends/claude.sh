# claude 后端：claude -p。参数已用 `claude --help`（2.1.331）核实。
be_argv() {
  argv=(claude -p --model "$MODEL" --output-format stream-json --verbose)
  if [ -n "$EFFORT" ]; then argv+=(--effort "$EFFORT"); fi
  case $SANDBOX in
    workspace-write) argv+=(--permission-mode acceptEdits);;
    read-only) argv+=(--permission-mode plan);;
    danger-full-access) argv+=(--dangerously-skip-permissions);;
  esac
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
    if not isinstance(o,dict) or o.get("type")!="result": continue
    u=o.get("usage") if isinstance(o.get("usage"),dict) else {}
    c=n(o.get("total_cost_usd"))
    if c is not None: cost=c; source="claude:result.total_cost_usd"
    parts=[n(u.get("input_tokens")),n(u.get("output_tokens")),n(u.get("cache_creation_input_tokens"))]
    if any(p is not None for p in parts):
        tokens=int(sum(p for p in parts if p is not None)); source=source or "claude:result.usage"
print(json.dumps({"tokens":tokens,"cost_usd":cost,"source":source}))
PY
}
