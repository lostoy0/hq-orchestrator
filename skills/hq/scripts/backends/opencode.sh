# opencode 后端：opencode run（V2）。依据 GitHub sst/opencode 2026-11-25 的 `opencode run --help` 测试夹具与
# 源码 packages/cli-rs/crates/cli/src/commands/run.rs、run/prompt.rs，未实机运行：
#   - 没有消息参数时读完整个 stdin 作为消息；--model provider/model#variant；--format json 逐行输出事件；
#   - 每步结束输出 {"type":"step_finish","part":{"cost":…,"tokens":{"input","output","reasoning","cache":{"read","write"}}}}；
#   - --auto 自动批准未被显式拒绝的权限；--agent 选 agent（read-only 用内置只读的 plan）。
be_argv() {
  local m=$MODEL
  if [ -n "$EFFORT" ]; then
    case "$m" in *#*) NOTES="${NOTES}model 已带 #variant，忽略 --effort $EFFORT；";; *) m="$m#$EFFORT";; esac
  fi
  argv=(opencode run --model "$m" --format json --title "hq/$ID")
  case $SANDBOX in
    read-only) argv+=(--agent plan);;
    workspace-write) argv+=(--auto)
      NOTES="${NOTES}opencode 没有只限工作区的沙箱：--auto 会批准未被显式拒绝的全部权限（含 shell），隔离只靠 worktree 和任务说明；";;
    danger-full-access) argv+=(--auto);;
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
    if not isinstance(o,dict) or o.get("type")!="step_finish": continue
    p=o.get("part") if isinstance(o.get("part"),dict) else {}
    t=p.get("tokens") if isinstance(p.get("tokens"),dict) else None
    if t is not None:
        cache=t.get("cache") if isinstance(t.get("cache"),dict) else {}
        # 每步的用量各自独立，逐步相加；input 不含缓存读取（cache.read 单列，按口径不计）。待实机核对。
        s=sum(v for v in (n(t.get("input")),n(t.get("output")),n(t.get("reasoning")),n(cache.get("write"))) if v is not None)
        tokens=(tokens or 0)+int(s); source="opencode:step_finish"
    c=n(p.get("cost"))
    if c is not None: cost=round((cost or 0)+c,6)
print(json.dumps({"tokens":tokens,"cost_usd":cost,"source":source}))
PY
}
