#!/usr/bin/env bash
# cli-worker.sh 自测：假 CLI + 临时 git 仓库。
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$HERE/skills/hq/scripts/cli-worker.sh"
export PATH="$HERE/tests/fixtures/fake-cli:$PATH"
pass=0; fail=0
ok()  { echo "PASS: $1"; pass=$((pass+1)); }
bad() { echo "FAIL: $1 ($2)"; fail=$((fail+1)); }
jget() { python3 -c 'import json,sys; v=json.loads(sys.argv[1])[sys.argv[2]]; print("null" if v is None else v)' "$1" "$2"; }

T=$(mktemp -d); trap 'for p in "$T"/repo/.hq/workers/*/pid; do [ -f "$p" ] && kill -KILL -- "-$(cat "$p")" 2>/dev/null; done; rm -rf "$T"' EXIT
git init -q "$T/repo" && cd "$T/repo" || exit 1
git config user.email t@t; git config user.name t
echo hi > f; git add f; git commit -qm init
echo "do the task" > "$T/brief.md"
W() { bash "$SCRIPT" "$@"; }
wait_state() { # id want 最多等 8 秒
  local i s; for i in $(seq 1 40); do s=$(jget "$(W status --id "$1")" state); [ "$s" = "$2" ] && { echo "$s"; return; }; sleep 0.2; done; echo "$s"
}

# 1 start codex
out=$(W start --id c1 --cli codex --model m1 --effort low --brief "$T/brief.md" 2>&1)
[ -d .hq/worktrees/c1 ] && git show-ref --verify --quiet refs/heads/hq/c1 && ok "start creates worktree and branch" || bad "start creates worktree and branch" "$out"
[ -f .hq/workers/c1/pid ] && [ -f .hq/workers/c1/cmd ] && [ -f .hq/workers/c1/started_at ] && ok "state files written" || bad "state files written" "$(ls .hq/workers/c1)"
git check-ignore -q .hq/ && ok ".hq/ is ignored" || bad ".hq/ is ignored" "not ignored"
[ -z "$(git status --porcelain)" ] && ok "git status clean (no .hq noise)" || bad "git status clean" "$(git status --porcelain)"
s=$(jget "$(W status --id c1)" state); [ "$s" = running ] && ok "status running" || bad "status running" "$s"
s=$(wait_state c1 done); [ "$s" = done ] && ok "status running -> done" || bad "status -> done" "$s"
st=$(W status --id c1); [ "$(jget "$st" exit_code)" = 0 ] && [ "$(jget "$st" ended_at)" != null ] && ok "exit_code and ended_at recorded" || bad "exit_code/ended_at" "$st"
grep -q 'exec -m m1' .hq/workers/c1/out.jsonl && grep -q 'model_reasoning_effort=low' .hq/workers/c1/out.jsonl && grep -q -- '-s workspace-write --json' .hq/workers/c1/out.jsonl && ok "codex args passed" || bad "codex args passed" "$(head -1 .hq/workers/c1/out.jsonl)"
grep -q 'do the task' .hq/workers/c1/out.jsonl && ok "brief delivered via stdin" || bad "brief delivered" "no"

# usage codex: (1000-400)+50=650
u=$(W usage --id c1)
[ "$(jget "$u" tokens)" = 650 ] && [ "$(jget "$u" cost_usd)" = null ] && ok "usage codex parsed" || bad "usage codex" "$u"

# 2 失败
FAKE_EXIT=3 FAKE_NO_USAGE=1 W start --id f1 --cli codex --model m1 --brief "$T/brief.md" >/dev/null 2>&1
s=$(wait_state f1 failed); [ "$s" = failed ] && [ "$(jget "$(W status --id f1)" exit_code)" = 3 ] && ok "failure -> failed" || bad "failure -> failed" "$s"
u=$(W usage --id f1); [ "$(jget "$u" tokens)" = null ] && [ "$(jget "$u" cost_usd)" = null ] && ok "usage null when unparsable" || bad "usage null" "$u"

# 3 claude
W start --id k1 --cli claude --model m2 --effort high --brief "$T/brief.md" >/dev/null 2>&1
s=$(wait_state k1 done); [ "$s" = done ] && ok "claude worker done" || bad "claude worker done" "$s"
grep -q -- '-p --model m2 --output-format stream-json' .hq/workers/k1/out.jsonl && grep -q -- '--effort high' .hq/workers/k1/out.jsonl && ok "claude args passed" || bad "claude args" "$(head -1 .hq/workers/k1/out.jsonl)"
u=$(W usage --id k1); [ "$(jget "$u" tokens)" = 150 ] && [ "$(jget "$u" cost_usd)" = 0.25 ] && ok "usage claude parsed (cache_read excluded)" || bad "usage claude" "$u"

# 4 stop
FAKE_SLEEP=60 W start --id s1 --cli codex --model m1 --brief "$T/brief.md" >/dev/null 2>&1
sleep 0.5; pid=$(cat .hq/workers/s1/pid)
W stop --id s1 >/dev/null 2>&1
if ! kill -0 "$pid" 2>/dev/null && [ "$(jget "$(W status --id s1)" state)" != running ] && [ -d .hq/worktrees/s1 ]; then ok "stop ends process, keeps worktree"; else bad "stop" "$(W status --id s1)"; fi

# 5 分支重复
W start --id c1 --cli codex --model m1 --brief "$T/brief.md" >/dev/null 2>&1; rc=$?
[ $rc -ne 0 ] && [ $rc -ne 2 ] && ok "duplicate branch errors" || bad "duplicate branch errors" "rc=$rc"

# 6 list / unknown
n=$(W list | wc -l); [ "$n" -ge 4 ] && ok "list shows workers" || bad "list" "$n"
[ "$(jget "$(W status --id nope)" state)" = unknown ] && ok "status unknown for missing id" || bad "status unknown" ""

# 7 非法参数 → 2
chk() { local name=$1; shift; W "$@" >/dev/null 2>&1; local rc=$?; [ $rc -eq 2 ] && ok "invalid args exit 2: $name" || bad "invalid args exit 2: $name" "rc=$rc"; }
chk "no command"
chk "unknown command" bogus
chk "start missing args" start --id x
chk "bad cli" start --id x --cli foo --model m --brief "$T/brief.md"
chk "bad id" start --id 'a b' --cli codex --model m --brief "$T/brief.md"
chk "missing brief file" start --id x --cli codex --model m --brief "$T/none"
chk "bad sandbox" start --id x --cli codex --model m --brief "$T/brief.md" --sandbox yolo
chk "unknown flag" status --id x --zzz 1
chk "status without id" status

echo "----"
echo "SUMMARY: $pass passed, $fail failed"
[ $fail -eq 0 ]
