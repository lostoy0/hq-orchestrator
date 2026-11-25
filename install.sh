#!/usr/bin/env bash
# hq-orchestrator 安装脚本：只复制文件，不修改任何用户配置。
# 兼容 bash 3.2（macOS 自带），不使用关联数组。
# 一行安装：curl -fsSL https://raw.githubusercontent.com/lostoy0/hq-orchestrator/v<版本>/install.sh | bash -s -- --host auto
set -u
HQ_VERSION=0.4.8
HQ_REPO_URL_DEFAULT=https://github.com/lostoy0/hq-orchestrator.git

usage() {
  cat <<U
用法: install.sh --host <宿主> [--scope user|project] [--project-dir <路径>] [--layout minimal|per-host]
                 [--with-agents [--model-map 'T0=<模型>,…']] [--with-codex-agents] [--force] [--dry-run]
      install.sh --list    [--host <宿主>] [--scope ...]   只显示检测结果、已装副本和安装计划，不写入
      install.sh --update  [--scope ...]                   把本脚本装过的副本更新到当前版本
      install.sh --uninstall [--scope ...]                 删除本脚本装过的副本（只删有安装记录的）
  <宿主>: auto（自动检测本机已装的工具）| all | claude,codex,dsh,opencode,cursor,gemini 中的一个或多个（逗号分隔）
          both 为旧写法，等同 claude,codex
  --layout minimal  （默认）只装到能覆盖所选工具的最少目录，避免同一工具读到重复技能
           per-host 每个工具装到各自的专属目录
  目录对照见 adapters/skill-dirs.tsv、adapters/hosts.tsv。例如 ~/.agents/skills 可被 codex、dsh、opencode、gemini 读取，
  ~/.claude/skills 可被 claude、opencode、cursor 读取；所以 dsh 也会读取 ~/.agents/skills，装过 codex 的不必再装 dsh。
  --with-agents      同时安装所选宿主的子代理档位模板 hq-t0…hq-t4（目前 codex、opencode、gemini；见 adapters/agent-dirs.tsv）
  --model-map <映射> 生成模板时填入模型（只能配合一个宿主的模板）：codex、gemini 写模型名；opencode 写 provider/model[#variant]
  --with-codex-agents 只装 Codex 模板（旧写法，不管 --host 是什么都装）
  不在仓库里运行时（如 curl | bash），先把 v\$HQ_VERSION（可用 HQ_REF 覆盖）下载到 ~/.hq-orchestrator/<ref> 再安装。
退出码: 0 成功; 2 参数非法; 3 目标已存在(加 --force 覆盖); 4 没有可操作的对象; 5 下载失败
U
}
die2() { echo "错误: $1" >&2; usage >&2; exit 2; }

# ---------- 引导：不在仓库里运行时先下载 ----------
src="${BASH_SOURCE[0]:-}"
ROOT=""
if [ -n "$src" ] && [ -f "$src" ]; then ROOT="$(cd "$(dirname "$src")" && pwd)"; fi
if [ -z "$ROOT" ] || [ ! -f "$ROOT/skills/hq/SKILL.md" ]; then
  ref=${HQ_REF:-v$HQ_VERSION}
  url=${HQ_REPO_URL:-$HQ_REPO_URL_DEFAULT}
  cache=${HQ_CACHE_DIR:-$HOME/.hq-orchestrator}
  dst="$cache/$(printf '%s' "$ref" | tr '/' '_')"
  # 版本标签（vX.Y.Z）下载过就复用；分支名每次重新下载
  if [ ! -f "$dst/install.sh" ] || ! printf '%s' "$ref" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+$'; then
    command -v git >/dev/null 2>&1 || { echo "错误: 需要 git 才能下载 hq-orchestrator" >&2; exit 5; }
    mkdir -p "$cache" || exit 5
    tmp=$(mktemp -d "$cache/.dl.XXXXXX") || exit 5
    echo "下载 hq-orchestrator $ref <- $url"
    if ! git clone -q --depth 1 --branch "$ref" "$url" "$tmp/src" 2>"$tmp/err"; then
      cat "$tmp/err" >&2; rm -rf "$tmp"
      echo "错误: 下载失败（ref=${ref}）。可设置 HQ_REF=<标签或分支> 后重试" >&2; exit 5
    fi
    rm -rf "$dst"; mv "$tmp/src" "$dst"; rm -rf "$tmp"
  fi
  [ -f "$dst/skills/hq/SKILL.md" ] || { echo "错误: 下载内容不完整: $dst" >&2; exit 5; }
  exec bash "$dst/install.sh" "$@"
fi

# ---------- 参数 ----------
action=install; host=""; scope="user"; pdir=""; layout="minimal"; agents=0; codex_agents=0; mmap=""; force=0; dry=0
while [ $# -gt 0 ]; do
  case "$1" in
    --host) [ $# -ge 2 ] || die2 "--host 缺少值"; host=$2; shift 2;;
    --scope) [ $# -ge 2 ] || die2 "--scope 缺少值"; scope=$2; shift 2;;
    --project-dir) [ $# -ge 2 ] || die2 "--project-dir 缺少值"; pdir=$2; shift 2;;
    --layout) [ $# -ge 2 ] || die2 "--layout 缺少值"; layout=$2; shift 2;;
    --with-agents) agents=1; shift;;
    --with-codex-agents) codex_agents=1; shift;;
    --model-map) [ $# -ge 2 ] || die2 "--model-map 缺少值"; mmap=$2; shift 2;;
    --force) force=1; shift;;
    --dry-run) dry=1; shift;;
    --list) action=list; shift;;
    --update) action=update; shift;;
    --uninstall) action=uninstall; shift;;
    -h|--help) usage; exit 0;;
    *) die2 "未知参数: $1";;
  esac
done
case "$scope" in user|project) ;; *) die2 "--scope 必须是 user|project";; esac
case "$layout" in minimal|per-host) ;; *) die2 "--layout 必须是 minimal|per-host";; esac
if [ "$scope" = project ]; then
  [ -n "$pdir" ] || pdir=$PWD
  [ -d "$pdir" ] || die2 "项目目录不存在: $pdir"
  pdir="$(cd "$pdir" && pwd)"
fi
[ "$action" = install ] && [ -z "$host" ] && die2 "安装需要 --host（不确定就用 --host auto）"
[ "$action" = list ] && [ -z "$host" ] && host=auto

# ---------- 读登记表 ----------
[ -f "$ROOT/adapters/hosts.tsv" ] && [ -f "$ROOT/adapters/skill-dirs.tsv" ] || {
  echo "错误: 缺少登记表 adapters/hosts.tsv 或 adapters/skill-dirs.tsv" >&2; exit 2; }
D_KEY=(); D_USER=(); D_PROJ=()
while read -r k u p; do
  case "$k" in ''|\#*) continue;; esac
  D_KEY+=("$k"); D_USER+=("$u"); D_PROJ+=("$p")
done <"$ROOT/adapters/skill-dirs.tsv"
H_ID=(); H_LEVEL=(); H_PRIM=(); H_READS=(); H_CMD=(); H_DIR=(); H_NOTE=()
while read -r id lv pr rd cmd dd note; do
  case "$id" in ''|\#*) continue;; esac
  H_ID+=("$id"); H_LEVEL+=("$lv"); H_PRIM+=("$pr"); H_READS+=("$rd"); H_CMD+=("$cmd"); H_DIR+=("$dd"); H_NOTE+=("$note")
done <"$ROOT/adapters/hosts.tsv"

expand() { local s=$1; s=${s/@DSH_HOME@/${DSH_HOME:-$HOME/.dsh}}; s=${s/#\~/$HOME}; printf '%s' "$s"; }
host_idx() { local i; for i in "${!H_ID[@]}"; do [ "${H_ID[$i]}" = "$1" ] && { echo "$i"; return 0; }; done; return 1; }
dir_idx()  { local i; for i in "${!D_KEY[@]}"; do [ "${D_KEY[$i]}" = "$1" ] && { echo "$i"; return 0; }; done; return 1; }
dir_path() { local i; i=$(dir_idx "$1") || return 1
  if [ "$scope" = project ]; then printf '%s/%s' "$pdir" "${D_PROJ[$i]}"; else expand "${D_USER[$i]}"; fi; }
reads() { local i; i=$(host_idx "$1"); case ",${H_READS[$i]}," in *",$2,"*) return 0;; esac; return 1; }
in_list() { local x n=$1; shift; for x in "$@"; do [ "$x" = "$n" ] && return 0; done; return 1; }

detect() {  # 本机装了哪些工具：检测命令（HQ_NO_CMD_DETECT=1 时跳过，测试用）或检测目录存在
  local i out=()
  for i in "${!H_ID[@]}"; do
    local c=${H_CMD[$i]} d=${H_DIR[$i]} hit=0
    if [ "${HQ_NO_CMD_DETECT:-0}" != 1 ] && [ "$c" != - ] && command -v "$c" >/dev/null 2>&1; then hit=1; fi
    if [ "$d" != - ] && [ -d "$(expand "$d")" ]; then hit=1; fi
    if [ "${H_ID[$i]}" = dsh ] && [ -n "${DSH_HOME:-}" ]; then hit=1; fi
    [ $hit = 1 ] && out+=("${H_ID[$i]}")
  done
  [ ${#out[@]} -gt 0 ] && echo "${out[@]}"
}

# 解析 --host 为宿主列表 HOSTS
HOSTS=()
resolve_hosts() {
  local v=$1 h
  case "$v" in
    auto) local d; d=$(detect)
          [ -n "$d" ] || { echo "未检测到任何已知工具（${H_ID[*]}）。请用 --host 指定。" >&2; exit 4; }
          for h in $d; do HOSTS+=("$h"); done;;
    all) HOSTS=("${H_ID[@]}");;
    both) HOSTS=(claude codex);;
    *) local IFS=,; for h in $v; do
         [ -n "$h" ] || continue
         host_idx "$h" >/dev/null || die2 "--host 不认识的宿主: ${h}（可选 auto|all|${H_ID[*]}；both 为旧写法）"
         in_list "$h" ${HOSTS[@]+"${HOSTS[@]}"} || HOSTS+=("$h")
       done
       [ ${#HOSTS[@]} -gt 0 ] || die2 "--host 为空";;
  esac
}

# 计算要装的目录 KEYS
KEYS=()
plan_dirs() {
  local h i k
  if [ "$layout" = per-host ]; then
    for h in "${HOSTS[@]}"; do i=$(host_idx "$h"); k=${H_PRIM[$i]}
      in_list "$k" ${KEYS[@]+"${KEYS[@]}"} || KEYS+=("$k"); done
    return
  fi
  # 贪心最小覆盖：每轮选能覆盖最多未覆盖宿主的目录；打平时优先“某个未覆盖宿主的专属目录”，再按 skill-dirs.tsv 顺序
  local left=("${HOSTS[@]}")
  while [ ${#left[@]} -gt 0 ]; do
    local best="" bn=0 bp=0
    for k in "${D_KEY[@]}"; do
      local n=0 p=0
      for h in "${left[@]}"; do
        reads "$h" "$k" && n=$((n+1))
        i=$(host_idx "$h"); [ "${H_PRIM[$i]}" = "$k" ] && p=1
      done
      if [ $n -gt $bn ] || { [ $n -eq $bn ] && [ $n -gt 0 ] && [ $p -gt $bp ]; }; then best=$k; bn=$n; bp=$p; fi
    done
    [ -n "$best" ] || { echo "错误: 登记表有误，无法覆盖: ${left[*]}" >&2; exit 2; }
    KEYS+=("$best")
    local nl=(); for h in "${left[@]}"; do reads "$h" "$best" || nl+=("$h"); done
    left=(${nl[@]+"${nl[@]}"})
  done
}
readers_of() { local h out=(); for h in "${HOSTS[@]}"; do reads "$h" "$1" && out+=("$h"); done; echo "${out[*]}"; }

run() { if [ $dry -eq 1 ]; then echo "[dry-run] $*"; else "$@"; fi; }
json_hosts() { local h s=""; for h in "$@"; do s="$s${s:+,}\"$h\""; done; printf '[%s]' "$s"; }
write_marker() {  # $1=技能目录 $2=dir key $3=hosts json
  [ $dry -eq 1 ] && return 0
  printf '{"name":"%s","version":"%s","source":"%s","dir_key":"%s","scope":"%s","hosts":%s,"installed_at":"%s"}\n' \
    "$(basename "$1")" "$HQ_VERSION" "$ROOT" "$2" "$scope" "$3" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$1/.hq-install.json"
}
marker_hosts() { sed -n 's/.*"hosts":\(\[[^]]*\]\).*/\1/p' "$1" 2>/dev/null; }
marker_version() { sed -n 's/.*"version":"\([^"]*\)".*/\1/p' "$1" 2>/dev/null; }
write_skill_path() {  # 个人范围：记下 hq 技能目录，供 SKILL.md 查找脚本
  [ "$scope" = user ] && [ $dry -eq 0 ] || return 0
  mkdir -p "$HOME/.hq" && printf '%s\n' "$1" >"$HOME/.hq/skill-path"
}

# 扫描所有登记目录里的已装副本：输出 “key|路径|状态|版本”
scan_installed() {
  local k b s
  for k in "${D_KEY[@]}"; do b=$(dir_path "$k")
    for s in hq hq-retro; do
      if [ -f "$b/$s/.hq-install.json" ]; then echo "$k|$b/$s|managed|$(marker_version "$b/$s/.hq-install.json")"
      elif [ -f "$b/$s/SKILL.md" ]; then echo "$k|$b/$s|unmanaged|"; fi
    done
  done
}

# ---------- --list ----------
if [ "$action" = list ]; then
  echo "检测到的工具（${scope} 范围）："
  det=" $(detect) "
  for i in "${!H_ID[@]}"; do
    case "$det" in *" ${H_ID[$i]} "*) m="✓";; *) m="·";; esac
    echo "  $m ${H_ID[$i]} (${H_LEVEL[$i]})"
  done
  echo "已装副本："
  found=$(scan_installed)
  if [ -z "$found" ]; then echo "  （无）"; else
    echo "$found" | while IFS='|' read -r k p st v; do
      if [ "$st" = managed ]; then echo "  $p  v$v"; else echo "  $p  （无安装记录：旧版本或手动复制）"; fi
    done
  fi
  if [ "$host" = auto ] && [ "$det" = "  " ]; then echo "安装计划：未检测到工具，请用 --host 指定"; exit 0; fi
  resolve_hosts "$host"; plan_dirs
  echo "安装计划（--host $host --layout ${layout}）："
  for k in "${KEYS[@]}"; do echo "  $(dir_path "$k")/{hq,hq-retro}  <- $(readers_of "$k")"; done
  exit 0
fi

# ---------- --update / --uninstall ----------
if [ "$action" = update ] || [ "$action" = uninstall ]; then
  found=$(scan_installed | grep '|managed|' || true)
  legacy=$(scan_installed | grep '|unmanaged|' || true)
  if [ -n "$legacy" ]; then
    echo "提示: 以下副本没有安装记录（v0.3 及更早或手动复制），不会被处理；需要时用 --host <宿主> --force 重装或手动删除："
    echo "$legacy" | while IFS='|' read -r k p st v; do echo "  $p"; done
  fi
  [ -n "$found" ] || { echo "没有找到本脚本安装的副本（${scope} 范围）。" >&2; exit 4; }
  first=""
  while IFS='|' read -r k p st v; do
    s=$(basename "$p")
    if [ "$action" = uninstall ]; then
      run rm -rf "$p"; echo "删除 $p"
      if [ "$scope" = user ] && [ $dry -eq 0 ] && [ "$(cat "$HOME/.hq/skill-path" 2>/dev/null)" = "$p" ]; then rm -f "$HOME/.hq/skill-path"; fi
    else
      hj=$(marker_hosts "$p/.hq-install.json"); [ -n "$hj" ] || hj='[]'
      run rm -rf "$p"; run cp -r "$ROOT/skills/$s" "$p"; write_marker "$p" "$k" "$hj"
      echo "更新 $p  v$v -> v$HQ_VERSION"
      [ "$s" = hq ] && [ -z "$first" ] && first=$p
    fi
  done <<EOF
$found
EOF
  [ -n "$first" ] && write_skill_path "$first"
  [ "$action" = uninstall ] && echo "完成。子代理模板（如装过）不会自动删除：~/.codex/agents/hq-t*.toml、~/.config/opencode/agents/hq-t*.md、~/.gemini/agents/hq-t*.md，或项目里的 .codex/agents/、.opencode/agents/、.gemini/agents/。Gemini 扩展请用 gemini extensions uninstall hq-orchestrator。"
  exit 0
fi

# ---------- 安装 ----------
resolve_hosts "$host"
plan_dirs

# 子代理档位模板（--with-agents / --with-codex-agents）：目录见 adapters/agent-dirs.tsv；
# 不带 --model-map 时复制仓库里预生成的 adapters/<格式>/agents/，带时用 adapters/render.sh 现场生成。
A_FMT=(); A_USER=(); A_PROJ=(); A_ENV=(); A_EXT=()
if [ -f "$ROOT/adapters/agent-dirs.tsv" ]; then
  while read -r f u p e x; do
    case "$f" in ''|\#*) continue;; esac
    A_FMT+=("$f"); A_USER+=("$u"); A_PROJ+=("$p"); A_ENV+=("$e"); A_EXT+=("$x")
  done <"$ROOT/adapters/agent-dirs.tsv"
fi
FMTS=()
for i in ${A_FMT[@]+"${!A_FMT[@]}"}; do
  f=${A_FMT[$i]}
  if { [ $agents -eq 1 ] && in_list "$f" "${HOSTS[@]}"; } || { [ $codex_agents -eq 1 ] && [ "$f" = codex ]; }; then FMTS+=("$i"); fi
done
if [ $codex_agents -eq 1 ] && [ ${#FMTS[@]} -eq 0 ]; then FMTS=(-1); fi   # 登记表缺失时按旧路径处理
[ -n "$mmap" ] && [ ${#FMTS[@]} -ne 1 ] && die2 "--model-map 需要且只能对应一个宿主的模板（当前 ${#FMTS[@]} 个）；分多次安装"
[ -n "$mmap" ] && [ "${FMTS[0]}" = -1 ] && die2 "缺少 adapters/agent-dirs.tsv，无法使用 --model-map"
AG_SRC=(); AG_DST=(); AG_NOTE=()
render_tmp=""
for i in ${FMTS[@]+"${FMTS[@]}"}; do
  if [ "$i" = -1 ]; then f=codex; ext=toml; envv=CODEX_AGENTS_DIR; ud='~/.codex/agents'; pd=.codex/agents
  else f=${A_FMT[$i]}; ext=${A_EXT[$i]}; envv=${A_ENV[$i]}; ud=${A_USER[$i]}; pd=${A_PROJ[$i]}; fi
  eval "ov=\${$envv:-}"
  if [ -n "$ov" ]; then adir=$ov; elif [ "$scope" = user ]; then adir=$(expand "$ud"); else adir="$pdir/$pd"; fi
  sdir="$ROOT/adapters/$f/agents"
  if [ -n "$mmap" ]; then
    render_tmp=$(mktemp -d); trap 'rm -rf "$render_tmp"' EXIT
    bash "$ROOT/adapters/render.sh" --format "$f" --out "$render_tmp" --model-map "$mmap" || exit 2
    sdir=$render_tmp
  fi
  n=0
  for src in "$sdir"/hq-t*."$ext"; do
    [ -e "$src" ] || continue
    AG_SRC+=("$src"); AG_DST+=("$adir/$(basename "$src")"); n=$((n+1))
  done
  if [ $n -eq 0 ]; then AG_NOTE+=("提示: 未找到 adapters/$f/agents/hq-t*.$ext 模板，跳过 $f 的子代理模板")
  elif [ -n "$mmap" ]; then AG_NOTE+=("$f 子代理模板已按 --model-map 填入模型；没填的档位见文件内注释")
  elif [ "$f" = codex ]; then AG_NOTE+=("codex 子代理模板里的 model 是占位符，必须按 adapters/codex/README.md 替换（或重装时加 --model-map）")
  else AG_NOTE+=("$f 子代理模板未设置 model（继承父会话模型，档位不生效）；按 adapters/$f/README.md 用 --model-map 重装"); fi
done
if [ $agents -eq 1 ] && [ ${#FMTS[@]} -eq 0 ]; then AG_NOTE+=("提示: 所选宿主（${HOSTS[*]}）没有子代理模板，--with-agents 不起作用"); fi

echo "宿主: ${HOSTS[*]}  范围: $scope  布局: $layout"
# 先检查所有目标（技能和 agent 模板），避免装一半
for k in "${KEYS[@]}"; do base=$(dir_path "$k")
  for s in hq hq-retro; do
    if [ -e "$base/$s" ] && [ $force -eq 0 ]; then
      echo "错误: 目标已存在: $base/$s ；如需覆盖请加 --force（或用 --update 更新本脚本装过的副本）" >&2; exit 3
    fi
  done
done
for dst in ${AG_DST[@]+"${AG_DST[@]}"}; do
  if [ -e "$dst" ] && [ $force -eq 0 ]; then
    echo "错误: 目标已存在: $dst ；如需覆盖请加 --force" >&2; exit 3
  fi
done

first=""
for k in "${KEYS[@]}"; do base=$(dir_path "$k"); rd=$(readers_of "$k")
  for s in hq hq-retro; do
    run mkdir -p "$base"
    [ -e "$base/$s" ] && run rm -rf "$base/$s"
    run cp -r "$ROOT/skills/$s" "$base/$s"
    write_marker "$base/$s" "$k" "$(json_hosts $rd)"
    echo "安装 $s -> $base/${s}（供 $rd 读取）"
  done
  [ -z "$first" ] && first="$base/hq"
done
write_skill_path "$first"

# 已装 Gemini 扩展时提醒：用户目录的技能优先于扩展里的同名技能
if in_list gemini "${HOSTS[@]}" && [ -d "$HOME/.gemini/extensions/hq-orchestrator" ]; then
  echo "注意: 已装 Gemini 扩展 hq-orchestrator；Gemini CLI 会优先用这次装到用户/项目目录的副本，扩展里的同名技能被覆盖。建议只留一种（卸载扩展: gemini extensions uninstall hq-orchestrator）。"
fi
# 同一工具从多个目录读到同名技能时提醒
for h in "${HOSTS[@]}"; do n=0
  for k in "${KEYS[@]}"; do reads "$h" "$k" && n=$((n+1)); done
  [ $n -gt 1 ] && echo "注意: $h 会从 $n 个目录读到同名技能 hq（多个工具共用时无法避免），按该工具的规则只加载其中一份。"
done

for i in ${AG_SRC[@]+"${!AG_SRC[@]}"}; do
  run mkdir -p "$(dirname "${AG_DST[$i]}")"
  run cp "${AG_SRC[$i]}" "${AG_DST[$i]}"
  echo "安装子代理模板 -> ${AG_DST[$i]}"
done
for m in ${AG_NOTE[@]+"${AG_NOTE[@]}"}; do echo "$m"; done

echo "完成（v${HQ_VERSION}）。下一步:"
for h in "${HOSTS[@]}"; do i=$(host_idx "$h"); echo "  ${H_NOTE[$i]}"; done
exit 0
