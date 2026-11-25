#!/usr/bin/env bash
# install.sh 自测：临时 HOME 和临时项目目录。
INST="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/install.sh"
pass=0; fail=0
ok()  { echo "PASS: $1"; pass=$((pass+1)); }
bad() { echo "FAIL: $1 ($2)"; fail=$((fail+1)); }

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
fresh() { rm -rf "$T/h" "$T/p" "$T/ag"; mkdir -p "$T/h" "$T/p"; }
inst() { HOME="$T/h" CODEX_AGENTS_DIR="$T/ag" bash "$INST" "$@" >"$T/out" 2>&1; }

# 1-4. 宿主 x 范围
for h in claude codex; do for s in user project; do
  fresh
  [ $h = claude ] && sub=.claude/skills || sub=.agents/skills
  [ $s = user ] && base="$T/h/$sub" || base="$T/p/$sub"
  inst --host $h --scope $s --project-dir "$T/p"; rc=$?
  if [ $rc = 0 ] && [ -f "$base/hq/SKILL.md" ] && [ -f "$base/hq-retro/SKILL.md" ]; then ok "$h/$s 装到正确目录"
  else bad "$h/$s" "rc=$rc"; fi
done; done

# 5. both
fresh; inst --host both; rc=$?
[ $rc = 0 ] && [ -f "$T/h/.claude/skills/hq/SKILL.md" ] && [ -f "$T/h/.agents/skills/hq/SKILL.md" ] && ok "both 两处都装" || bad "both" "rc=$rc"

# 6. dry-run 不写入
fresh; inst --host both --scope project --project-dir "$T/p" --dry-run --with-codex-agents; rc=$?
n=$(find "$T/h" "$T/p" "$T/ag" -type f 2>/dev/null | wc -l)
[ $rc = 0 ] && [ "$n" = 0 ] && [ ! -e "$T/ag" ] && ok "dry-run 不写入" || bad "dry-run" "rc=$rc files=$n"

# 7. 已存在无 --force => 3，且不覆盖
fresh; inst --host claude; echo keep >"$T/h/.claude/skills/hq/marker"
inst --host claude; rc=$?
[ $rc = 3 ] && [ -f "$T/h/.claude/skills/hq/marker" ] && ok "已存在退出码 3 且不覆盖" || bad "exists" "rc=$rc"

# 8. --force 覆盖
inst --host claude --force; rc=$?
[ $rc = 0 ] && [ ! -f "$T/h/.claude/skills/hq/marker" ] && [ -f "$T/h/.claude/skills/hq/SKILL.md" ] && ok "--force 覆盖成功" || bad "force" "rc=$rc"

# 9. 模板不存在时跳过（用临时副本，缺 adapters 目录）
fresh; cp -r "$(dirname "$INST")/skills" "$T/repo_skills_tmp" 2>/dev/null
mkdir -p "$T/repo"; mv "$T/repo_skills_tmp" "$T/repo/skills"; cp "$INST" "$T/repo/install.sh"
HOME="$T/h" CODEX_AGENTS_DIR="$T/ag" bash "$T/repo/install.sh" --host codex --with-codex-agents >"$T/out" 2>&1; rc=$?
[ $rc = 0 ] && grep -q "跳过" "$T/out" && [ ! -e "$T/ag" ] && ok "agent 模板不存在时跳过" || bad "agents skip" "rc=$rc"

# 10. agent 模板存在时复制
mkdir -p "$T/repo/adapters/codex/agents"; echo 'x=1' >"$T/repo/adapters/codex/agents/hq-t0.toml"
fresh
HOME="$T/h" CODEX_AGENTS_DIR="$T/ag" bash "$T/repo/install.sh" --host codex --with-codex-agents >"$T/out" 2>&1; rc=$?
[ $rc = 0 ] && [ -f "$T/ag/hq-t0.toml" ] && ok "agent 模板复制到 CODEX_AGENTS_DIR" || bad "agents copy" "rc=$rc"

# 10b. 不设 CODEX_AGENTS_DIR：个人范围 -> ~/.codex/agents，项目范围 -> <项目>/.codex/agents
fresh
HOME="$T/h" bash "$INST" --host codex --with-codex-agents >"$T/out" 2>&1; rc=$?
[ $rc = 0 ] && [ -f "$T/h/.codex/agents/hq-t2.toml" ] && [ ! -e "$T/p/.codex" ] && ok "个人范围 agent 装到 ~/.codex/agents" || bad "agents user dir" "rc=$rc"
fresh
HOME="$T/h" bash "$INST" --host codex --scope project --project-dir "$T/p" --with-codex-agents >"$T/out" 2>&1; rc=$?
[ $rc = 0 ] && [ -f "$T/p/.codex/agents/hq-t2.toml" ] && [ ! -e "$T/h/.codex" ] && ok "项目范围 agent 装到 <项目>/.codex/agents" || bad "agents project dir" "rc=$rc"

# 10c. agent 目标已存在 => 3，且技能也不装（不装一半）
fresh; mkdir -p "$T/p/.codex/agents"; echo keep >"$T/p/.codex/agents/hq-t0.toml"
HOME="$T/h" bash "$INST" --host codex --scope project --project-dir "$T/p" --with-codex-agents >"$T/out" 2>&1; rc=$?
[ $rc = 3 ] && [ ! -e "$T/p/.agents/skills/hq" ] && grep -q keep "$T/p/.codex/agents/hq-t0.toml" && ok "agent 已存在退出码 3 且不装一半" || bad "agents exists" "rc=$rc"

# 11. 非法参数 => 2
for args in "" "--host foo" "--host claude --scope x" "--host claude --bogus" "--host"; do
  fresh; inst $args; rc=$?
  [ $rc = 2 ] && ok "非法参数 '$args' 退出码 2" || bad "invalid '$args'" "rc=$rc"
done

echo "----"
echo "SUMMARY: $pass passed, $fail failed"
[ $fail -eq 0 ]
