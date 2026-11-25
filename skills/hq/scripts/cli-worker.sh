#!/usr/bin/env bash
# HQ W 通道：在独立 git worktree 里后台启动 codex exec / claude -p 作为 worker 进程。
# 用法:
#   cli-worker.sh start --id <id> --cli codex|claude --model <m> [--effort <e>] --brief <文件> [--base <分支>]
#                       [--sandbox read-only|workspace-write|danger-full-access] [--allow-dangerous]
#   默认 sandbox 为 workspace-write。danger-full-access 必须同时加 --allow-dangerous，否则报错退出（码 2）。
#   cli-worker.sh status|stop|usage --id <id>
#   cli-worker.sh list
# 状态目录 .hq/workers/<id>/: out.jsonl log cmd pid exit_code started_at ended_at meta
# worktree: .hq/worktrees/<id>，分支 hq/<id>。只依赖 bash、coreutils、git、python3。
set -u

usage() {
  cat >&2 <<'U'
用法:
  cli-worker.sh start --id <id> --cli codex|claude --model <m> [--effort <e>] --brief <文件> [--base <分支>] [--sandbox read-only|workspace-write|danger-full-access] [--allow-dangerous]
  （danger-full-access 必须同时加 --allow-dangerous）
  cli-worker.sh status --id <id>
  cli-worker.sh stop --id <id>
  cli-worker.sh usage --id <id>
  cli-worker.sh list
U
  exit 2
}
die() { echo "cli-worker: $*" >&2; exit 1; }

[ $# -ge 1 ] || usage
CMD=$1; shift
ID=""; CLI=""; MODEL=""; EFFORT=""; BRIEF=""; BASE=""; SANDBOX="workspace-write"; ALLOW_DANGER=0
while [ $# -gt 0 ]; do
  if [ "$1" = --allow-dangerous ]; then ALLOW_DANGER=1; shift; continue; fi
  [ $# -ge 2 ] || usage
  case $1 in
    --id) ID=$2;; --cli) CLI=$2;; --model) MODEL=$2;; --effort) EFFORT=$2;;
    --brief) BRIEF=$2;; --base) BASE=$2;; --sandbox) SANDBOX=$2;;
    *) usage;;
  esac
  shift 2
done

ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || die "不在 git 仓库内"
WDIR="$ROOT/.hq/workers"

need_id() { [[ $ID =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || usage; }
now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
epoch() { python3 -c 'import sys,datetime;print(int(datetime.datetime.strptime(sys.argv[1],"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc).timestamp()))' "$1"; }
rd() { [ -r "$1" ] && cat "$1" || true; }

alive() { local p; p=$(rd "$WDIR/$ID/pid"); [ -n "$p" ] && kill -0 "$p" 2>/dev/null; }

do_status() {
  local d="$WDIR/$ID" pid ec st en state="unknown" minutes=null
  [ -d "$d" ] || { echo "{\"id\":\"$ID\",\"state\":\"unknown\",\"pid\":null,\"exit_code\":null,\"started_at\":null,\"ended_at\":null,\"minutes\":null}"; return 0; }
  pid=$(rd "$d/pid"); ec=$(rd "$d/exit_code"); st=$(rd "$d/started_at"); en=$(rd "$d/ended_at")
  if [ -n "$ec" ]; then
    if [ "$ec" = 0 ]; then state=done; else state=failed; fi
  elif alive; then state=running
  else state=unknown   # 进程没了也没有退出码（被 KILL 或宿主重启）
  fi
  python3 - "$ID" "$state" "$pid" "$ec" "$st" "$en" <<'PY'
import sys,json,datetime
i,state,pid,ec,st,en=sys.argv[1:7]
def p(s):
    return datetime.datetime.strptime(s,"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc) if s else None
a,b=p(st),p(en)
if a and not b and state=="running": b=datetime.datetime.now(datetime.timezone.utc)
m=round((b-a).total_seconds()/60,1) if a and b else None
print(json.dumps({"id":i,"state":state,"pid":int(pid) if pid else None,"exit_code":int(ec) if ec!="" else None,
 "started_at":st or None,"ended_at":en or None,"minutes":m}))
PY
}

do_start() {
  need_id
  [ -n "$CLI" ] && [ -n "$MODEL" ] && [ -n "$BRIEF" ] || usage
  case $CLI in codex|claude) ;; *) usage;; esac
  case $SANDBOX in read-only|workspace-write|danger-full-access) ;; *) usage;; esac
  # 高风险：codex 的 danger-full-access 与 claude 的 --dangerously-skip-permissions 都关闭全部防护，
  # 只能由调用方显式确认，不能靠默认值或单个参数开启
  if [ "$SANDBOX" = danger-full-access ] && [ "$ALLOW_DANGER" != 1 ]; then
    echo "cli-worker: --sandbox danger-full-access 需要同时传 --allow-dangerous（会关闭全部沙箱/权限防护）" >&2; exit 2
  fi
  [ -r "$BRIEF" ] || { echo "cli-worker: brief 文件不可读: $BRIEF" >&2; exit 2; }
  BRIEF=$(cd "$(dirname "$BRIEF")" && pwd)/$(basename "$BRIEF")
  [ -n "$BASE" ] || BASE=HEAD
  local br="hq/$ID" wt="$ROOT/.hq/worktrees/$ID" d="$WDIR/$ID"
  git -C "$ROOT" show-ref --verify --quiet "refs/heads/$br" && die "分支 $br 已存在"
  [ -e "$wt" ] && die "worktree 已存在: $wt"
  [ -e "$d" ] && die "worker 目录已存在: $d"
  # .hq/ 必须被 git 忽略；没忽略就写进 .git/info/exclude
  if ! git -C "$ROOT" check-ignore -q .hq/ 2>/dev/null && ! git -C "$ROOT" check-ignore -q .hq/x 2>/dev/null; then
    local ex; ex=$(git -C "$ROOT" rev-parse --git-path info/exclude)
    case $ex in /*) ;; *) ex="$ROOT/$ex";; esac
    mkdir -p "$(dirname "$ex")"; echo ".hq/" >> "$ex"
  fi
  git -C "$ROOT" worktree add -q -b "$br" "$wt" "$BASE" || die "创建 worktree 失败"
  mkdir -p "$d"

  local -a argv; local note=""
  if [ "$CLI" = codex ]; then
    # 简报经 stdin 传入（codex exec 的 PROMPT 为 "-" 时读 stdin），避免超长命令行
    argv=(codex exec -m "$MODEL")
    [ -n "$EFFORT" ] && argv+=(-c "model_reasoning_effort=$EFFORT")
    argv+=(-s "$SANDBOX" --json -)
  else
    argv=(claude -p --model "$MODEL" --output-format stream-json --verbose)
    if [ -n "$EFFORT" ]; then argv+=(--effort "$EFFORT"); fi
    case $SANDBOX in
      workspace-write) argv+=(--permission-mode acceptEdits);;
      read-only) argv+=(--permission-mode plan);;
      danger-full-access) argv+=(--dangerously-skip-permissions);;
    esac
  fi
  { printf '%q ' "${argv[@]}"; printf '< %q\n' "$BRIEF"; } > "$d/cmd"
  : > "$d/out.jsonl"; : > "$d/log"
  now > "$d/started_at"; printf '%s\n' "$CLI" > "$d/cli"
  # runner：在 worktree 里执行 CLI，结束后写 exit_code 与 ended_at
  cat > "$d/run.sh" <<'R'
#!/usr/bin/env bash
d=$1; wt=$2; brief=$3; shift 3
cd "$wt" || { echo 127 > "$d/exit_code"; date -u +%Y-%m-%dT%H:%M:%SZ > "$d/ended_at"; exit 127; }
"$@" < "$brief" > "$d/out.jsonl" 2> "$d/log"
ec=$?
echo "$ec" > "$d/exit_code"; date -u +%Y-%m-%dT%H:%M:%SZ > "$d/ended_at"
R
  setsid nohup bash "$d/run.sh" "$d" "$wt" "$BRIEF" "${argv[@]}" > /dev/null 2>&1 < /dev/null &
  echo $! > "$d/pid"
  echo "{\"id\":\"$ID\",\"branch\":\"$br\",\"worktree\":\"$wt\",\"pid\":$(cat "$d/pid")}"
}

do_stop() {
  need_id
  [ -d "$WDIR/$ID" ] || die "worker 不存在: $ID"
  local pid; pid=$(rd "$WDIR/$ID/pid")
  if alive; then
    # run.sh 是 setsid 的进程组组长：对整个进程组发信号
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
    local i; for i in $(seq 1 20); do alive || break; sleep 0.5; done
    if alive; then kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null; sleep 0.3; fi
  fi
  if [ ! -s "$WDIR/$ID/ended_at" ]; then now > "$WDIR/$ID/ended_at"; fi
  [ -s "$WDIR/$ID/exit_code" ] || echo 143 > "$WDIR/$ID/exit_code"
  do_status
}

do_usage() {
  need_id
  local f="$WDIR/$ID/out.jsonl"
  [ -f "$f" ] || die "worker 不存在: $ID"
  python3 - "$f" "$(rd "$WDIR/$ID/cli")" <<'PY'
import sys,json
f,cli=sys.argv[1:3]
def n(x): return x if isinstance(x,(int,float)) and not isinstance(x,bool) else None
tokens=None; cost=None; source=None
for line in open(f,encoding="utf-8",errors="replace"):
    try: o=json.loads(line)
    except Exception: continue
    if not isinstance(o,dict): continue
    if cli=="claude" and o.get("type")=="result":
        u=o.get("usage") if isinstance(o.get("usage"),dict) else {}
        c=n(o.get("total_cost_usd"))
        if c is not None: cost=c; source="claude:result.total_cost_usd"
        parts=[n(u.get("input_tokens")),n(u.get("output_tokens")),n(u.get("cache_creation_input_tokens"))]
        if any(p is not None for p in parts):
            tokens=int(sum(p for p in parts if p is not None)); source=source or "claude:result.usage"
    elif cli=="codex":
        u=o.get("usage")
        if not isinstance(u,dict) and isinstance(o.get("msg"),dict): u=o["msg"].get("usage") or o["msg"].get("info")
        if isinstance(u,dict):
            # codex turn.completed.usage：input_tokens 已含 cached_input_tokens（cache_read），按口径扣除；
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

do_list() {
  [ -d "$WDIR" ] || exit 0
  local d
  for d in "$WDIR"/*/; do [ -d "$d" ] || continue; ID=$(basename "$d"); do_status; done
}

case $CMD in
  start) do_start;;
  status) need_id; do_status;;
  stop) do_stop;;
  usage) do_usage;;
  list) [ -z "$ID$CLI$MODEL$BRIEF" ] || usage; do_list;;
  *) usage;;
esac
