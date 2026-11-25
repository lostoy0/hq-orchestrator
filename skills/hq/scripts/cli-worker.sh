#!/usr/bin/env bash
# HQ W 通道：在独立 git worktree 里后台启动 CLI worker 进程（codex exec / claude -p / opencode run / gemini / cursor-agent）。
# 每个 CLI 的参数拼装和用量解析在 backends/<cli>.sh（接口见 backends/README.md）。
# 用法:
#   cli-worker.sh start --id <id> --cli <cli> --model <m> [--effort <e>] --brief <文件> [--base <分支>]
#                       [--sandbox read-only|workspace-write|danger-full-access] [--allow-dangerous]
#                       [--env-file <文件>] [--label <名称>]
#   --env-file：KEY=VALUE 文件，只注入这个 worker 进程（如 Kimi 的 ANTHROPIC_BASE_URL/ANTHROPIC_AUTH_TOKEN）；
#               不能被同组或其他用户读取（chmod 600），值不写进 cmd/notes/输出。
#   --label：辅助执行者名称（如 kimi、codex），写进 status/usage 的 label 字段，供记录 model 为 <label>:<模型>。
#   默认 sandbox 为 workspace-write。danger-full-access 必须同时加 --allow-dangerous，否则报错退出（码 2）。
#   cli-worker.sh status|stop|usage --id <id>
#   cli-worker.sh list
# 状态目录 .hq/workers/<id>/: out.jsonl log cmd pid exit_code started_at ended_at cli notes
# worktree: .hq/worktrees/<id>，分支 hq/<id>。只依赖 bash、coreutils、git、python3。
set -u
BE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/backends"
CLIS=""
for f in "$BE_DIR"/*.sh; do [ -e "$f" ] && CLIS="$CLIS${CLIS:+|}$(basename "$f" .sh)"; done

usage() {
  cat >&2 <<U
用法:
  cli-worker.sh start --id <id> --cli <$CLIS> --model <m> [--effort <e>] --brief <文件> [--base <分支>] [--sandbox read-only|workspace-write|danger-full-access] [--allow-dangerous] [--env-file <文件>] [--label <名称>]
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
ID=""; CLI=""; MODEL=""; EFFORT=""; BRIEF=""; BASE=""; SANDBOX="workspace-write"; ALLOW_DANGER=0; ENV_FILE=""; LABEL=""
while [ $# -gt 0 ]; do
  if [ "$1" = --allow-dangerous ]; then ALLOW_DANGER=1; shift; continue; fi
  [ $# -ge 2 ] || usage
  case $1 in
    --id) ID=$2;; --cli) CLI=$2;; --model) MODEL=$2;; --effort) EFFORT=$2;;
    --brief) BRIEF=$2;; --base) BASE=$2;; --sandbox) SANDBOX=$2;;
    --env-file) ENV_FILE=$2;; --label) LABEL=$2;;
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
  local d="$WDIR/$ID" pid ec st en lb state="unknown" minutes=null
  [ -d "$d" ] || { echo "{\"id\":\"$ID\",\"state\":\"unknown\",\"pid\":null,\"exit_code\":null,\"started_at\":null,\"ended_at\":null,\"minutes\":null,\"label\":null}"; return 0; }
  pid=$(rd "$d/pid"); ec=$(rd "$d/exit_code"); st=$(rd "$d/started_at"); en=$(rd "$d/ended_at"); lb=$(rd "$d/label")
  if [ -n "$ec" ]; then
    if [ "$ec" = 0 ]; then state=done; else state=failed; fi
  elif alive; then state=running
  else state=unknown   # 进程没了也没有退出码（被 KILL 或宿主重启）
  fi
  python3 - "$ID" "$state" "$pid" "$ec" "$st" "$en" "$lb" <<'PY'
import sys,json,datetime
i,state,pid,ec,st,en,lb=sys.argv[1:8]
def p(s):
    return datetime.datetime.strptime(s,"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc) if s else None
a,b=p(st),p(en)
if a and not b and state=="running": b=datetime.datetime.now(datetime.timezone.utc)
m=round((b-a).total_seconds()/60,1) if a and b else None
print(json.dumps({"id":i,"state":state,"pid":int(pid) if pid else None,"exit_code":int(ec) if ec!="" else None,
 "started_at":st or None,"ended_at":en or None,"minutes":m,"label":lb.strip() or None}))
PY
}

do_start() {
  need_id
  [ -n "$CLI" ] && [ -n "$MODEL" ] && [ -n "$BRIEF" ] || usage
  case "|$CLIS|" in *"|$CLI|"*) ;; *) usage;; esac
  case $SANDBOX in read-only|workspace-write|danger-full-access) ;; *) usage;; esac
  # 高风险：各 CLI 的 danger-full-access 映射（codex 原样、claude --dangerously-skip-permissions、opencode/cursor 的全自动批准、gemini yolo）都关闭全部防护，
  # 只能由调用方显式确认，不能靠默认值或单个参数开启
  if [ "$SANDBOX" = danger-full-access ] && [ "$ALLOW_DANGER" != 1 ]; then
    echo "cli-worker: --sandbox danger-full-access 需要同时传 --allow-dangerous（会关闭全部沙箱/权限防护）" >&2; exit 2
  fi
  [ -r "$BRIEF" ] || { echo "cli-worker: brief 文件不可读: $BRIEF" >&2; exit 2; }
  BRIEF=$(cd "$(dirname "$BRIEF")" && pwd)/$(basename "$BRIEF")
  if [ -n "$LABEL" ] && ! [[ $LABEL =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$ ]]; then usage; fi
  if [ -n "$ENV_FILE" ]; then
    [ -f "$ENV_FILE" ] && [ -r "$ENV_FILE" ] || { echo "cli-worker: env 文件不可读: $ENV_FILE" >&2; exit 2; }
    # 密钥文件不能被同组或其他用户读取
    python3 -c 'import os,sys,stat;sys.exit(1 if os.stat(sys.argv[1]).st_mode & (stat.S_IRWXG|stat.S_IRWXO) else 0)' "$ENV_FILE" \
      || { echo "cli-worker: env 文件权限过宽（需 chmod 600）: $ENV_FILE" >&2; exit 2; }
    ENV_FILE=$(cd "$(dirname "$ENV_FILE")" && pwd)/$(basename "$ENV_FILE")
  fi
  [ -n "$BASE" ] || BASE=HEAD
  # 先拼好命令（后端可能拒绝某些组合），再建 worktree，避免失败时留下分支
  local -a argv; STDIN_SRC=brief; NOTES=""
  # shellcheck source=/dev/null
  . "$BE_DIR/$CLI.sh"
  be_argv || { echo "cli-worker: $CLI 不支持 --sandbox $SANDBOX 的组合${NOTES:+：$NOTES}" >&2; exit 2; }
  local stdin_file=$BRIEF; [ "$STDIN_SRC" = null ] && stdin_file=/dev/null
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

  { [ -n "$ENV_FILE" ] && printf 'env_file=%q ' "$ENV_FILE"; printf '%q ' "${argv[@]}"; printf '< %q\n' "$stdin_file"; } > "$d/cmd"
  [ -n "$LABEL" ] && printf '%s\n' "$LABEL" > "$d/label"
  [ -n "$NOTES" ] && printf '%s\n' "$NOTES" > "$d/notes"
  : > "$d/out.jsonl"; : > "$d/log"
  now > "$d/started_at"; printf '%s\n' "$CLI" > "$d/cli"
  # runner：在 worktree 里执行 CLI，结束后写 exit_code 与 ended_at
  cat > "$d/run.sh" <<'R'
#!/usr/bin/env bash
d=$1; wt=$2; brief=$3; envf=$4; shift 4
# env 文件只在本进程内生效，不回显
if [ -n "$envf" ]; then set -a; . "$envf" || { echo 126 > "$d/exit_code"; date -u +%Y-%m-%dT%H:%M:%SZ > "$d/ended_at"; exit 126; }; set +a; fi
cd "$wt" || { echo 127 > "$d/exit_code"; date -u +%Y-%m-%dT%H:%M:%SZ > "$d/ended_at"; exit 127; }
"$@" < "$brief" > "$d/out.jsonl" 2> "$d/log"
ec=$?
echo "$ec" > "$d/exit_code"; date -u +%Y-%m-%dT%H:%M:%SZ > "$d/ended_at"
R
  setsid nohup bash "$d/run.sh" "$d" "$wt" "$stdin_file" "$ENV_FILE" "${argv[@]}" > /dev/null 2>&1 < /dev/null &
  echo $! > "$d/pid"
  python3 -c 'import json,sys;print(json.dumps({"id":sys.argv[1],"branch":sys.argv[2],"worktree":sys.argv[3],"pid":int(sys.argv[4]),"notes":sys.argv[5] or None,"label":sys.argv[6] or None},ensure_ascii=False))' "$ID" "$br" "$wt" "$(cat "$d/pid")" "$NOTES" "$LABEL"
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
  local cli; cli=$(rd "$WDIR/$ID/cli")
  if [ -n "$cli" ] && [ -f "$BE_DIR/$cli.sh" ]; then
    # shellcheck source=/dev/null
    . "$BE_DIR/$cli.sh"; be_usage "$f"
  else
    echo '{"tokens":null,"cost_usd":null,"source":null}'
  fi | python3 -c 'import json,sys;o=json.loads(sys.stdin.read());o["label"]=sys.argv[1] or None;print(json.dumps(o,ensure_ascii=False))' "$(rd "$WDIR/$ID/label" | tr -d '\n')"
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
