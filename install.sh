#!/usr/bin/env bash
# hq-orchestrator 安装脚本：只复制文件，不修改任何用户配置。
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<U
用法: ./install.sh --host claude|codex|both [--scope user|project] [--project-dir <路径>]
                   [--with-codex-agents] [--force] [--dry-run]
退出码: 0 成功; 2 参数非法; 3 目标已存在(加 --force 覆盖)
U
}
die2() { echo "错误: $1" >&2; usage >&2; exit 2; }

host=""; scope="user"; pdir=""; agents=0; force=0; dry=0
while [ $# -gt 0 ]; do
  case "$1" in
    --host) [ $# -ge 2 ] || die2 "--host 缺少值"; host=$2; shift 2;;
    --scope) [ $# -ge 2 ] || die2 "--scope 缺少值"; scope=$2; shift 2;;
    --project-dir) [ $# -ge 2 ] || die2 "--project-dir 缺少值"; pdir=$2; shift 2;;
    --with-codex-agents) agents=1; shift;;
    --force) force=1; shift;;
    --dry-run) dry=1; shift;;
    -h|--help) usage; exit 0;;
    *) die2 "未知参数: $1";;
  esac
done
case "$host" in claude|codex|both) ;; *) die2 "--host 必须是 claude|codex|both";; esac
case "$scope" in user|project) ;; *) die2 "--scope 必须是 user|project";; esac
if [ "$scope" = project ]; then
  [ -n "$pdir" ] || pdir=$PWD
  [ -d "$pdir" ] || die2 "项目目录不存在: $pdir"
fi

run() { if [ $dry -eq 1 ]; then echo "[dry-run] $*"; else "$@"; fi; }

# Codex 子代理档位模板（--with-codex-agents）：个人范围 ~/.codex/agents，项目范围 <项目>/.codex/agents
# （已按 Codex 官方文档核对，2026-11-25，未实机运行）。CODEX_AGENTS_DIR 可显式覆盖（测试用）。
adir=""; tpl=()
if [ $agents -eq 1 ]; then
  if [ -n "${CODEX_AGENTS_DIR:-}" ]; then adir=$CODEX_AGENTS_DIR
  elif [ "$scope" = user ]; then adir="$HOME/.codex/agents"
  else adir="$pdir/.codex/agents"; fi
  shopt -s nullglob
  tpl=("$ROOT"/adapters/codex/agents/*.toml)
  shopt -u nullglob
fi

# 先检查所有目标（技能和 agent 模板），避免装一半
targets=(); hosts=()
[ "$host" = both ] && hosts=(claude codex) || hosts=("$host")
for h in "${hosts[@]}"; do
  if [ "$h" = claude ]; then sub=.claude/skills; else sub=.agents/skills; fi
  if [ "$scope" = user ]; then base="$HOME/$sub"; else base="$pdir/$sub"; fi
  for s in hq hq-retro; do targets+=("$h|$base|$s"); done
done
for t in "${targets[@]}"; do
  IFS='|' read -r h base s <<<"$t"
  if [ -e "$base/$s" ] && [ $force -eq 0 ]; then
    echo "错误: 目标已存在: $base/$s ；如需覆盖请加 --force" >&2; exit 3
  fi
done
for f in "${tpl[@]}"; do
  dst="$adir/$(basename "$f")"
  if [ -e "$dst" ] && [ $force -eq 0 ]; then
    echo "错误: 目标已存在: $dst ；如需覆盖请加 --force" >&2; exit 3
  fi
done

for t in "${targets[@]}"; do
  IFS='|' read -r h base s <<<"$t"
  run mkdir -p "$base"
  [ -e "$base/$s" ] && run rm -rf "$base/$s"
  run cp -r "$ROOT/skills/$s" "$base/$s"
  echo "安装 $s -> $base/$s"
done

if [ $agents -eq 1 ]; then
  if [ ${#tpl[@]} -eq 0 ]; then
    echo "提示: 未找到 adapters/codex/agents/*.toml 模板，跳过 --with-codex-agents"
  else
    run mkdir -p "$adir"
    for f in "${tpl[@]}"; do
      dst="$adir/$(basename "$f")"
      run cp "$f" "$dst"
      echo "安装 agent 模板 -> $dst（请替换其中的 model 占位符）"
    done
  fi
fi

echo "完成。下一步:"
for h in "${hosts[@]}"; do
  if [ "$h" = claude ]; then echo "  Claude Code: 重启会话后输入 /hq"
  else echo "  Codex: 按 skills/hq/references/hosts/codex.md 的技能调用方式使用"; fi
done
exit 0
