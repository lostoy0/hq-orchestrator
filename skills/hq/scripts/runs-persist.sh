#!/usr/bin/env bash
# 把 .hq/runs/*.jsonl（运行记录）保存进项目仓库，让云端容器回收后数据不丢；复盘时再取回来。
# 用法:
#   runs-persist.sh save branch [--dir .hq/runs] [--branch hq/runs] [--remote origin]
#       写进专用分支（默认 hq/runs，文件放在 runs/ 下，只追加、不合并），并推送。不碰工作区和当前分支。
#   runs-persist.sh save commit [--dir .hq/runs]
#       提交到当前分支（git add -f，只提交运行记录文件），不推送，跟本批改动一起推。
#   runs-persist.sh fetch [--dir .hq/runs-archive] [--branch hq/runs] [--remote origin]
#       把专用分支上的记录取到本地目录，供 metrics.py / hq-retro 读取。
# 输出一行结果（SAVED / NOCHANGE / PUSH_FAILED / FETCHED），退出码:
#   0 成功或无变化; 1 不在 git 仓库等错误; 2 参数非法; 3 推送失败（本地 ref 已更新，可改用 commit 模式）;
#   4 没有可保存的记录 / 远程和本地都没有该分支。
# 只依赖 bash、coreutils、git。
set -u

usage() { sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }
die() { echo "runs-persist: $*" >&2; exit 1; }

[ $# -ge 1 ] || usage
CMD=$1; shift
MODE=""
if [ "$CMD" = save ]; then
  [ $# -ge 1 ] || usage
  MODE=$1; shift
  case $MODE in branch|commit) ;; *) usage;; esac
elif [ "$CMD" != fetch ]; then
  usage
fi
DIR=""; BRANCH=hq/runs; REMOTE=origin
while [ $# -gt 0 ]; do
  [ $# -ge 2 ] || usage
  case $1 in
    --dir) DIR=$2;; --branch) BRANCH=$2;; --remote) REMOTE=$2;;
    *) usage;;
  esac
  shift 2
done
git rev-parse --git-dir >/dev/null 2>&1 || die "不在 git 仓库里"
git check-ref-format "refs/heads/$BRANCH" || die "分支名不合法: $BRANCH"

has_remote() { git remote | grep -qx "$REMOTE"; }
RREF="refs/remotes/$REMOTE/$BRANCH"

# 拉取远程分支到 ${RREF}；成功返回 0
fetch_remote() {
  has_remote || return 1
  git fetch -q "$REMOTE" "+refs/heads/$BRANCH:$RREF" 2>/dev/null
}

# 输出要保存的文件（非空 .jsonl，按名字排序）
list_files() {
  local f
  for f in "$DIR"/*.jsonl; do [ -s "$f" ] && printf '%s\n' "$f"; done
}

ensure_identity() {
  git config user.email >/dev/null 2>&1 && return
  export GIT_AUTHOR_NAME=hq-orchestrator GIT_AUTHOR_EMAIL=hq@localhost
  export GIT_COMMITTER_NAME=hq-orchestrator GIT_COMMITTER_EMAIL=hq@localhost
}

# 在 parent（可空）的基础上写入记录文件，输出新 commit；没有变化时输出空
build_commit() {
  local parent=$1 tmp idx f b tree
  tmp=$(mktemp -d) || die "mktemp 失败"
  idx=$tmp/index
  if [ -n "$parent" ]; then GIT_INDEX_FILE=$idx git read-tree "$parent" || die "read-tree 失败"
  else GIT_INDEX_FILE=$idx git read-tree --empty; fi
  if ! GIT_INDEX_FILE=$idx git ls-files --error-unmatch README.md >/dev/null 2>&1; then
    printf '%s\n' "# hq 运行记录" "" \
      "由 hq-orchestrator 的 runs-persist.sh 自动写入（runs/<run_id>.jsonl），供 /hq-retro 复盘。" \
      "这是独立的历史分支，不要合并进其他分支。" >"$tmp/README.md"
    b=$(git hash-object -w "$tmp/README.md")
    GIT_INDEX_FILE=$idx git update-index --add --cacheinfo "100644,$b,README.md"
  fi
  while IFS= read -r f; do
    b=$(git hash-object -w "$f") || die "hash-object 失败: $f"
    GIT_INDEX_FILE=$idx git update-index --add --cacheinfo "100644,$b,runs/$(basename "$f")"
  done < <(list_files)
  tree=$(GIT_INDEX_FILE=$idx git write-tree)
  rm -rf "$tmp"
  if [ -n "$parent" ] && [ "$(git rev-parse "$parent^{tree}")" = "$tree" ]; then return 0; fi
  local n; n=$(list_files | wc -l | tr -d ' ')
  if [ -n "$parent" ]; then git commit-tree "$tree" -p "$parent" -m "hq runs: 保存 $n 个运行记录文件"
  else git commit-tree "$tree" -m "hq runs: 保存 $n 个运行记录文件"; fi
}

save_branch() {
  ensure_identity
  local try parent commit before
  for try in 1 2 3; do
    parent=""
    if fetch_remote; then parent=$(git rev-parse "$RREF")
    elif git rev-parse -q --verify "refs/heads/$BRANCH" >/dev/null; then parent=$(git rev-parse "refs/heads/$BRANCH"); fi
    commit=$(build_commit "$parent") || exit 1
    if [ -z "$commit" ]; then
      # 内容已在分支上；本地分支落后时顺手跟上
      [ -n "$parent" ] && git update-ref "refs/heads/$BRANCH" "$parent"
      echo "NOCHANGE branch=$BRANCH"; return 0
    fi
    git update-ref "refs/heads/$BRANCH" "$commit"
    if ! has_remote; then echo "PUSH_FAILED branch=$BRANCH commit=$commit reason=no-remote:$REMOTE"; exit 3; fi
    if git push -q "$REMOTE" "refs/heads/$BRANCH:refs/heads/$BRANCH" 2>/dev/null; then
      git update-ref "$RREF" "$commit"
      echo "SAVED branch=$BRANCH commit=$commit files=$(list_files | wc -l | tr -d ' ') pushed=yes"; return 0
    fi
    # 只有别的会话同时推送（远程前进了）才重试；其他原因（无权限、网络）直接放弃
    before=$parent
    fetch_remote || break
    [ "$(git rev-parse "$RREF")" = "$before" ] && break
  done
  echo "PUSH_FAILED branch=$BRANCH commit=$commit reason=push-rejected"
  exit 3
}

save_commit() {
  local files=() f
  while IFS= read -r f; do files+=("$f"); done < <(list_files)
  git add -f -- "${files[@]}" || die "git add 失败"
  if git diff --cached --quiet -- "${files[@]}"; then echo "NOCHANGE mode=commit"; return 0; fi
  ensure_identity
  git commit -q -m "hq runs: 保存 ${#files[@]} 个运行记录文件" --only -- "${files[@]}" || die "git commit 失败"
  echo "SAVED mode=commit commit=$(git rev-parse HEAD) files=${#files[@]} pushed=no"
}

if [ "$CMD" = save ]; then
  DIR=${DIR:-.hq/runs}
  [ -n "$(list_files)" ] || { echo "runs-persist: $DIR 下没有运行记录" >&2; exit 4; }
  if [ "$MODE" = branch ]; then save_branch; else save_commit; fi
  exit 0
fi

# fetch
DIR=${DIR:-.hq/runs-archive}
REF=""
if fetch_remote; then REF=$RREF
elif git rev-parse -q --verify "refs/heads/$BRANCH" >/dev/null; then REF=refs/heads/$BRANCH
else echo "runs-persist: 远程和本地都没有分支 $BRANCH" >&2; exit 4; fi
mkdir -p "$DIR" || die "无法创建目录 $DIR"
n=0
while IFS= read -r p; do
  case $p in runs/*.jsonl) ;; *) continue;; esac
  git show "$REF:$p" >"$DIR/$(basename "$p")" || die "读取失败: $p"
  n=$((n + 1))
done < <(git ls-tree -r --name-only "$REF" -- runs/)
echo "FETCHED branch=$BRANCH files=$n dir=$DIR"
