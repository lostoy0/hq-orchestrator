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

# usage codex: (1000-400)+50=650（reasoning 已含在 output 里，不重复加）
u=$(W usage --id c1)
[ "$(jget "$u" tokens)" = 650 ] && [ "$(jget "$u" cost_usd)" = null ] && ok "usage codex parsed" || bad "usage codex" "$u"

# 1b codex 沙箱不能写 .git：workspace-write 正常退出后由 cli-worker 代提交；read-only、失败、无改动都不提交
git log --oneline hq/c1 | wc -l | grep -qx ' *1' && ok "codex no changes -> no extra commit" || bad "codex no changes" "$(git log --oneline hq/c1)"
grep -q 'cli-worker' .hq/workers/c1/notes 2>/dev/null && ok "codex workspace-write notes mention proxy commit" || bad "codex notes" "$(cat .hq/workers/c1/notes 2>/dev/null)"
FAKE_WRITE=out.txt W start --id cw1 --cli codex --model m1 --brief "$T/brief.md" >/dev/null 2>&1
s=$(wait_state cw1 done)
[ "$s" = done ] && git show hq/cw1:out.txt >/dev/null 2>&1 && [ -z "$(git -C .hq/worktrees/cw1 status --porcelain)" ] && [ -z "$(git status --porcelain)" ] \
  && ok "codex workspace-write changes committed on hq/<id> by cli-worker" || bad "codex proxy commit" "$s $(git log --oneline hq/cw1 | head -2)"
FAKE_WRITE=out.txt W start --id cw2 --cli codex --model m1 --sandbox read-only --brief "$T/brief.md" >/dev/null 2>&1
s=$(wait_state cw2 done); ! git show hq/cw2:out.txt >/dev/null 2>&1 && ! grep -q 'cli-worker' .hq/workers/cw2/notes 2>/dev/null && ok "codex read-only -> no proxy commit" || bad "codex read-only commit" "$s"
FAKE_WRITE=out.txt FAKE_EXIT=3 W start --id cw3 --cli codex --model m1 --brief "$T/brief.md" >/dev/null 2>&1
s=$(wait_state cw3 failed); [ "$s" = failed ] && ! git show hq/cw3:out.txt >/dev/null 2>&1 && ok "codex failure -> no proxy commit" || bad "codex failure commit" "$s"

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

# 5b 默认 sandbox 与 danger-full-access 闸门
grep -q -- '--permission-mode acceptEdits' .hq/workers/k1/out.jsonl && ! grep -q -- 'dangerously' .hq/workers/k1/out.jsonl && ok "claude default sandbox is workspace-write (acceptEdits)" || bad "claude default sandbox" "$(head -1 .hq/workers/k1/out.jsonl)"
for c in claude codex; do
  W start --id d-$c --cli $c --model m --brief "$T/brief.md" --sandbox danger-full-access >/dev/null 2>&1; rc=$?
  [ $rc -eq 2 ] && [ ! -e .hq/worktrees/d-$c ] && ! git show-ref --verify --quiet refs/heads/hq/d-$c && ok "$c danger-full-access without --allow-dangerous -> exit 2, nothing created" || bad "$c danger gate" "rc=$rc"
done
W start --id da1 --cli claude --model m --brief "$T/brief.md" --sandbox danger-full-access --allow-dangerous >/dev/null 2>&1
s=$(wait_state da1 done); grep -q -- '--dangerously-skip-permissions' .hq/workers/da1/out.jsonl && ok "claude danger allowed with --allow-dangerous" || bad "claude danger allowed" "$s"
W start --id da2 --cli codex --model m --allow-dangerous --brief "$T/brief.md" --sandbox danger-full-access >/dev/null 2>&1
s=$(wait_state da2 done); grep -q -- '-s danger-full-access' .hq/workers/da2/out.jsonl && ok "codex danger allowed with --allow-dangerous" || bad "codex danger allowed" "$s"

# 6 list / unknown
n=$(W list | wc -l); [ "$n" -ge 4 ] && ok "list shows workers" || bad "list" "$n"
[ "$(jget "$(W status --id nope)" state)" = unknown ] && ok "status unknown for missing id" || bad "status unknown" ""

# 8 v0.4.2 新后端：opencode / gemini / cursor
W start --id o1 --cli opencode --model prov/mod --effort medium --brief "$T/brief.md" >"$T/o1.out" 2>&1
s=$(wait_state o1 done); [ "$s" = done ] && ok "opencode worker done" || bad "opencode done" "$s"
grep -q -- 'run --model prov/mod#medium --format json --title hq/o1 --auto' .hq/workers/o1/out.jsonl && grep -q 'do the task' .hq/workers/o1/out.jsonl && ok "opencode args (#effort, --auto) and stdin brief" || bad "opencode args" "$(head -1 .hq/workers/o1/out.jsonl)"
grep -q '"notes"' "$T/o1.out" && grep -q 'auto' .hq/workers/o1/notes && ok "opencode workspace-write writes notes" || bad "opencode notes" "$(cat "$T/o1.out")"
# (100+20+5+30)+(50+10+0+0)=215，cache.read 不计；cost 0.03
u=$(W usage --id o1); [ "$(jget "$u" tokens)" = 215 ] && [ "$(jget "$u" cost_usd)" = 0.03 ] && ok "usage opencode summed over steps" || bad "usage opencode" "$u"
W start --id o2 --cli opencode --model p/m#max --effort low --sandbox read-only --brief "$T/brief.md" >/dev/null 2>&1
s=$(wait_state o2 done); grep -q -- '--model p/m#max ' .hq/workers/o2/out.jsonl && grep -q -- '--agent plan' .hq/workers/o2/out.jsonl && ! grep -q -- '--auto' .hq/workers/o2/out.jsonl && ok "opencode read-only -> --agent plan, explicit variant kept" || bad "opencode ro" "$(head -1 .hq/workers/o2/out.jsonl)"

W start --id g1 --cli gemini --model gm --effort high --brief "$T/brief.md" >/dev/null 2>&1
s=$(wait_state g1 done); [ "$s" = done ] && ok "gemini worker done" || bad "gemini done" "$s"
grep -q -- '-m gm --output-format stream-json --approval-mode auto_edit -p' .hq/workers/g1/out.jsonl && grep -q 'do the task' .hq/workers/g1/out.jsonl && ok "gemini args and stdin brief" || bad "gemini args" "$(head -1 .hq/workers/g1/out.jsonl)"
grep -q '忽略 --effort high' .hq/workers/g1/notes && ok "gemini notes effort ignored" || bad "gemini notes" "$(cat .hq/workers/g1/notes 2>&1)"
# (1200-800)+100=500
u=$(W usage --id g1); [ "$(jget "$u" tokens)" = 500 ] && [ "$(jget "$u" cost_usd)" = null ] && ok "usage gemini (cached excluded)" || bad "usage gemini" "$u"
W start --id g2 --cli gemini --model gm --sandbox read-only --brief "$T/brief.md" >/dev/null 2>&1
s=$(wait_state g2 done); grep -q -- '--approval-mode plan' .hq/workers/g2/out.jsonl && ok "gemini read-only -> plan" || bad "gemini ro" "$s"

W start --id u1 --cli cursor --model cm --brief "$T/brief.md" >/dev/null 2>&1
s=$(wait_state u1 done); [ "$s" = done ] && ok "cursor worker done" || bad "cursor done" "$s"
grep -q -- '-p --output-format stream-json --model cm --force' .hq/workers/u1/out.jsonl && grep -q '"prompt","text":"do the task' .hq/workers/u1/out.jsonl && grep -q '"stdin","text":""' .hq/workers/u1/out.jsonl && ok "cursor args, brief as positional prompt, no stdin" || bad "cursor args" "$(head -3 .hq/workers/u1/out.jsonl)"
u=$(W usage --id u1); [ "$(jget "$u" tokens)" = 350 ] && ok "usage cursor (cache read excluded)" || bad "usage cursor" "$u"
W start --id u2 --cli cursor --model cm --sandbox read-only --brief "$T/brief.md" >/dev/null 2>&1
s=$(wait_state u2 done); ! grep -q -- '--force' .hq/workers/u2/out.jsonl && ok "cursor read-only -> no --force" || bad "cursor ro" "$s"

for c in opencode gemini cursor; do
  W start --id dd-$c --cli $c --model m/m --brief "$T/brief.md" --sandbox danger-full-access >/dev/null 2>&1; rc=$?
  [ $rc -eq 2 ] && [ ! -e .hq/worktrees/dd-$c ] && ok "$c danger without --allow-dangerous -> exit 2" || bad "$c danger gate" "rc=$rc"
done
W start --id dg --cli gemini --model m --brief "$T/brief.md" --sandbox danger-full-access --allow-dangerous >/dev/null 2>&1
s=$(wait_state dg done); grep -q -- '--approval-mode yolo' .hq/workers/dg/out.jsonl && ok "gemini danger -> yolo with --allow-dangerous" || bad "gemini danger" "$s"
FAKE_NO_USAGE=1 W start --id on --cli opencode --model p/m --brief "$T/brief.md" >/dev/null 2>&1
s=$(wait_state on done); u=$(W usage --id on); [ "$(jget "$u" tokens)" = null ] && ok "usage opencode null without step_finish" || bad "usage opencode null" "$u"
# 后端目录里每个 CLI 都有假 CLI（测试覆盖约定）
miss=""; for f in "$HERE"/skills/hq/scripts/backends/*.sh; do c=$(basename "$f" .sh); b=$c; [ $c = cursor ] && b=cursor-agent; [ -x "$HERE/tests/fixtures/fake-cli/$b" ] || miss="$miss $c"; done
[ -z "$miss" ] && ok "every backend has a fake CLI" || bad "fake CLI missing" "$miss"

# 9 v0.5.0 --env-file / --label（辅助执行者，如 Kimi 经 claude CLI）
printf 'ANTHROPIC_BASE_URL=https://kimi.example/anthropic\nANTHROPIC_AUTH_TOKEN=sekret-123\n' > "$T/kimi.env"; chmod 600 "$T/kimi.env"
out=$(W start --id km --cli claude --model kimi-x --env-file "$T/kimi.env" --label kimi --brief "$T/brief.md" 2>&1)
s=$(wait_state km done); [ "$s" = done ] && grep -q 'kimi.example/anthropic' .hq/workers/km/out.jsonl && ok "env-file injected into worker" || bad "env-file injected" "$s $(head -3 .hq/workers/km/out.jsonl)"
! grep -rq 'sekret-123' .hq/workers/km/cmd .hq/workers/km/log <(echo "$out") $( [ -f .hq/workers/km/notes ] && echo .hq/workers/km/notes ) && grep -q 'env_file=' .hq/workers/km/cmd && ok "secret not in cmd/log/output, cmd records path" || bad "secret leak" "$(cat .hq/workers/km/cmd)"
[ -z "${ANTHROPIC_AUTH_TOKEN:-}" ] && ok "env-file does not leak into caller" || bad "caller env" "set"
[ "$(jget "$out" label)" = kimi ] && [ "$(jget "$(W status --id km)" label)" = kimi ] && [ "$(jget "$(W usage --id km)" label)" = kimi ] && [ "$(jget "$(W usage --id km)" tokens)" = 150 ] && ok "label in start/status/usage" || bad "label" "$(W status --id km) $(W usage --id km)"
[ "$(jget "$(W status --id k1)" label)" = null ] && [ "$(jget "$(W usage --id k1)" label)" = null ] && ok "label null when not given" || bad "label null" "$(W status --id k1)"
chmod 644 "$T/kimi.env"
W start --id kp --cli claude --model m --env-file "$T/kimi.env" --brief "$T/brief.md" >/dev/null 2>&1; rc=$?
[ $rc -eq 2 ] && [ ! -e .hq/worktrees/kp ] && ok "env-file readable by others -> exit 2, nothing created" || bad "env-file perms" "rc=$rc"

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
chk "missing env file" start --id x --cli claude --model m --brief "$T/brief.md" --env-file "$T/none.env"
chk "bad label" start --id x --cli claude --model m --brief "$T/brief.md" --label "a b"

echo "----"
echo "SUMMARY: $pass passed, $fail failed"
[ $fail -eq 0 ]
