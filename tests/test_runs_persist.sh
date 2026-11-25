#!/usr/bin/env bash
# runs-persist.sh 自测：用本地 bare 仓库模拟远程，覆盖 branch / commit / fetch 和各失败分支。
SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/skills/hq/scripts/runs-persist.sh"
pass=0; fail=0
ok()  { echo "PASS: $1"; pass=$((pass+1)); }
bad() { echo "FAIL: $1 ($2)"; fail=$((fail+1)); }
check() { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "want [$3] got [$2]"; fi; }

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
export GIT_CONFIG_GLOBAL=$T/gitconfig GIT_CONFIG_NOSYSTEM=1
git config --global init.defaultBranch main
git init -q --bare "$T/remote.git"
mk() {  # mk 目录：克隆并建一个有 main 提交、忽略 .hq/ 的工作仓库
  git clone -q "$T/remote.git" "$1" 2>/dev/null
  ( cd "$1" && git config user.email t@t && git config user.name t
    if ! git rev-parse -q --verify origin/main >/dev/null; then
      echo ".hq/" >.gitignore && git add .gitignore && git commit -qm init && git push -q origin main
    else git checkout -q main; fi
    mkdir -p .hq/runs )
}
run() { ( cd "$1" && shift && bash "$SCRIPT" "$@" ); }

mk "$T/a"; mk "$T/b"

# 1. 没有记录
run "$T/a" save branch >/dev/null 2>&1; check "无记录时退出码 4" $? 4

# 2. 首次保存到专用分支
echo '{"type":"run","run_id":"r1"}' >"$T/a/.hq/runs/r1.jsonl"
: >"$T/a/.hq/runs/empty.jsonl"
out=$(run "$T/a" save branch); rc=$?
check "首次保存退出码 0" $rc 0
case $out in SAVED*pushed=yes*) ok "首次保存输出 SAVED";; *) bad "首次保存输出" "$out";; esac
files=$(git --git-dir="$T/remote.git" ls-tree -r --name-only hq/runs | tr '\n' ' ')
check "远程分支内容（跳过空文件，带 README）" "$files" "README.md runs/r1.jsonl "
check "工作区干净、仍在 main" "$(cd "$T/a" && git status --porcelain)|$(cd "$T/a" && git branch --show-current)" "|main"
check "main 没有被改动" "$(git --git-dir="$T/remote.git" log --oneline main | wc -l | tr -d ' ')" 1

# 3. 无变化
out=$(run "$T/a" save branch); check "重复保存为 NOCHANGE" "${out%% *}" NOCHANGE

# 4. 另一个会话保存不同的 run，再由 a 追加：两边记录都保留
echo '{"type":"run","run_id":"r2"}' >"$T/b/.hq/runs/r2.jsonl"
run "$T/b" save branch >/dev/null; check "b 保存退出码 0" $? 0
echo '{"type":"task","run_id":"r1","task_id":"t1"}' >>"$T/a/.hq/runs/r1.jsonl"
run "$T/a" save branch >/dev/null; check "a 追加保存退出码 0" $? 0
files=$(git --git-dir="$T/remote.git" ls-tree -r --name-only hq/runs runs/ | tr '\n' ' ')
check "并发保存后两个 run 都在" "$files" "runs/r1.jsonl runs/r2.jsonl "
check "r1 是最新内容" "$(git --git-dir="$T/remote.git" show hq/runs:runs/r1.jsonl | wc -l | tr -d ' ')" 2
git --git-dir="$T/remote.git" merge-base --is-ancestor "$(cd "$T/b" && git rev-parse hq/runs)" hq/runs
check "历史只追加（b 的提交是祖先）" $? 0

# 5. fetch 取回
out=$(run "$T/b" fetch); rc=$?
check "fetch 退出码 0" $rc 0
check "fetch 文件数" "$(ls "$T/b/.hq/runs-archive" | tr '\n' ' ')" "r1.jsonl r2.jsonl "
check "fetch 内容是最新的" "$(wc -l <"$T/b/.hq/runs-archive/r1.jsonl" | tr -d ' ')" 2
run "$T/b" fetch --branch nope >/dev/null 2>&1; check "分支不存在时 fetch 退出码 4" $? 4

# 6. 推送失败：本地 ref 已更新，退出码 3
mk "$T/c"; ( cd "$T/c" && git remote set-url origin "$T/missing.git" )
echo '{"type":"run","run_id":"r3"}' >"$T/c/.hq/runs/r3.jsonl"
out=$(run "$T/c" save branch); rc=$?
check "推送失败退出码 3" $rc 3
case $out in PUSH_FAILED*) ok "推送失败输出 PUSH_FAILED";; *) bad "推送失败输出" "$out";; esac
check "推送失败时本地分支已有记录" "$(cd "$T/c" && git show hq/runs:runs/r3.jsonl)" '{"type":"run","run_id":"r3"}'

# 7. commit 模式：只提交运行记录，不带上其他已暂存的改动，不推送
( cd "$T/c" && echo x >other.txt && git add other.txt )
out=$(run "$T/c" save commit); rc=$?
check "commit 模式退出码 0" $rc 0
check "commit 只含运行记录" "$(cd "$T/c" && git show --name-only --format= HEAD | tr '\n' ' ')" ".hq/runs/r3.jsonl "
check "其他暂存改动保留" "$(cd "$T/c" && git diff --cached --name-only)" "other.txt"
out=$(run "$T/c" save commit); check "commit 模式重复为 NOCHANGE" "${out%% *}" NOCHANGE

# 8. 参数和环境错误
run "$T/a" save nope >/dev/null 2>&1; check "非法模式退出码 2" $? 2
run "$T/a" bogus >/dev/null 2>&1; check "非法命令退出码 2" $? 2
( cd "$T" && bash "$SCRIPT" fetch >/dev/null 2>&1 ); check "不在仓库里退出码 1" $? 1

echo "passed=$pass failed=$fail"
[ $fail -eq 0 ]
