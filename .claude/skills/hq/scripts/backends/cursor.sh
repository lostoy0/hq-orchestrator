# cursor 后端：Cursor CLI（cursor-agent）打印模式。-p、--output-format stream-json、--model、--force 来自
# 官方参数页的检索摘要（2026-11-25），未实机运行；result 事件里的用量字段官方未写明，按常见字段名尝试解析。
#   - 提示词作为位置参数传入；不加 --force 时只提出修改、不落盘（用作 read-only）；
#   - 命令行没有思考深度参数；团队管理员可能禁用了无界面模式；需要 CURSOR_API_KEY 或已登录。
be_argv() {
  argv=(cursor-agent -p --output-format stream-json --model "$MODEL")
  case $SANDBOX in
    read-only) NOTES="${NOTES}cursor read-only：不加 --force，修改不会落盘；";;
    workspace-write) argv+=(--force)
      NOTES="${NOTES}cursor 没有只限工作区的沙箱：--force 允许未被规则拒绝的全部命令，隔离只靠 worktree 和任务说明；";;
    danger-full-access) argv+=(--force);;
  esac
  [ -n "$EFFORT" ] && NOTES="${NOTES}cursor 命令行不支持思考深度，忽略 --effort ${EFFORT}；"
  argv+=("$(cat "$BRIEF")")
  STDIN_SRC=null
}
be_usage() {
  python3 - "$1" <<'PY'
import sys,json
def n(x): return x if isinstance(x,(int,float)) and not isinstance(x,bool) else None
def g(d,*ks):
    for k in ks:
        v=n(d.get(k))
        if v is not None: return v
    return None
tokens=None; cost=None; source=None
for line in open(sys.argv[1],encoding="utf-8",errors="replace"):
    try: o=json.loads(line)
    except Exception: continue
    if not isinstance(o,dict) or o.get("type")!="result": continue
    u=o.get("usage") if isinstance(o.get("usage"),dict) else None
    if u:
        i=g(u,"input_tokens","inputTokens"); out=g(u,"output_tokens","outputTokens")
        cw=g(u,"cache_creation_input_tokens","cacheWriteTokens","cache_write_tokens") or 0
        if i is not None or out is not None:
            tokens=int((i or 0)+(out or 0)+cw); source="cursor:result.usage(待核实)"
    c=g(o,"total_cost_usd","cost_usd")
    if c is not None: cost=c
print(json.dumps({"tokens":tokens,"cost_usd":cost,"source":source}))
PY
}
