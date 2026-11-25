#!/usr/bin/env bash
# install.sh 自测：临时 HOME 和临时项目目录。
INST="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/install.sh"
pass=0; fail=0
unset DSH_HOME DSH_AGENTS_HOME   # 不受调用者环境影响
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

# 5b. dsh：个人范围 -> ${DSH_HOME:-~/.dsh}/skills，项目范围 -> <项目>/.dsh/skills
fresh; inst --host dsh; rc=$?
[ $rc = 0 ] && [ -f "$T/h/.dsh/skills/hq/SKILL.md" ] && [ -f "$T/h/.dsh/skills/hq-retro/SKILL.md" ] && [ ! -e "$T/h/.agents" ] && ok "dsh/user 装到 ~/.dsh/skills" || bad "dsh/user" "rc=$rc"
fresh; HOME="$T/h" DSH_HOME="$T/dh" bash "$INST" --host dsh >"$T/out" 2>&1; rc=$?
[ $rc = 0 ] && [ -f "$T/dh/skills/hq/SKILL.md" ] && [ ! -e "$T/h/.dsh" ] && ok "dsh/user 遵从 DSH_HOME" || bad "dsh DSH_HOME" "rc=$rc"; rm -rf "$T/dh"
fresh; HOME="$T/h" DSH_HOME="$T/dh" bash "$INST" --host dsh --scope project --project-dir "$T/p" >"$T/out" 2>&1; rc=$?
[ $rc = 0 ] && [ -f "$T/p/.dsh/skills/hq/SKILL.md" ] && [ ! -e "$T/dh" ] && ok "dsh/project 装到 <项目>/.dsh/skills" || bad "dsh/project" "rc=$rc"

# 5c. all（v0.4 起为全部登记宿主 + 最小目录集合）：只装 ~/.agents 和 ~/.claude 两处
fresh; inst --host all; rc=$?
[ $rc = 0 ] && [ -f "$T/h/.claude/skills/hq/SKILL.md" ] && [ -f "$T/h/.agents/skills/hq/SKILL.md" ] && [ ! -e "$T/h/.dsh" ] && [ ! -e "$T/h/.config" ] && [ ! -e "$T/h/.cursor" ] && [ ! -e "$T/h/.gemini" ] && ok "all 最小集合只装两处" || bad "all" "rc=$rc"
# 5c'. all --layout per-host：六个工具各自的专属目录
fresh; inst --host all --layout per-host; rc=$?
n=0; for d in .claude/skills .agents/skills .dsh/skills .config/opencode/skills .cursor/skills .gemini/skills; do [ -f "$T/h/$d/hq/SKILL.md" ] && n=$((n+1)); done
[ $rc = 0 ] && [ $n = 6 ] && ok "all per-host 六处都装" || bad "all per-host" "rc=$rc n=$n"

# 5d. both 仍兼容：只装 claude + codex
fresh; inst --host both; rc=$?
[ $rc = 0 ] && [ ! -e "$T/h/.dsh" ] && ok "both 兼容且不装 dsh" || bad "both compat" "rc=$rc"

# 5e. usage 说明 dsh 读 ~/.agents/skills
inst --help; grep -q "dsh 也会读取 ~/.agents/skills" "$T/out" && ok "usage 说明 dsh 共享 ~/.agents/skills" || bad "usage dsh note" "missing"

# 6. dry-run 不写入
fresh; inst --host all --scope project --project-dir "$T/p" --dry-run --with-codex-agents; rc=$?
n=$(find "$T/h" "$T/p" "$T/ag" -type f 2>/dev/null | wc -l | tr -d ' ')
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
mkdir -p "$T/repo/adapters"; mv "$T/repo_skills_tmp" "$T/repo/skills"; cp "$INST" "$T/repo/install.sh"
cp "$(dirname "$INST")"/adapters/*.tsv "$T/repo/adapters/"
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

# ---------- v0.4.0：新宿主、最小集合、auto、list/update/uninstall、引导下载 ----------
REPO="$(dirname "$INST")"
# 12. 新宿主单独安装到专属目录
fresh; inst --host opencode; rc=$?
[ $rc = 0 ] && [ -f "$T/h/.config/opencode/skills/hq/SKILL.md" ] && [ ! -e "$T/h/.agents" ] && ok "opencode/user 装到 ~/.config/opencode/skills" || bad "opencode/user" "rc=$rc"
fresh; inst --host cursor --scope project --project-dir "$T/p"; rc=$?
[ $rc = 0 ] && [ -f "$T/p/.cursor/skills/hq-retro/SKILL.md" ] && ok "cursor/project 装到 <项目>/.cursor/skills" || bad "cursor/project" "rc=$rc"
fresh; inst --host gemini; rc=$?
[ $rc = 0 ] && [ -f "$T/h/.gemini/skills/hq/SKILL.md" ] && ok "gemini/user 装到 ~/.gemini/skills" || bad "gemini/user" "rc=$rc"

# 13. 最小集合：共享目录优先，不给同一工具装两份
fresh; inst --host opencode,gemini; rc=$?
[ $rc = 0 ] && [ -f "$T/h/.agents/skills/hq/SKILL.md" ] && [ ! -e "$T/h/.config" ] && [ ! -e "$T/h/.gemini" ] && ok "opencode,gemini 只装 ~/.agents/skills" || bad "min opencode,gemini" "rc=$rc"
fresh; inst --host claude,cursor,opencode; rc=$?
[ $rc = 0 ] && [ -f "$T/h/.claude/skills/hq/SKILL.md" ] && [ ! -e "$T/h/.agents" ] && [ ! -e "$T/h/.cursor" ] && [ ! -e "$T/h/.config" ] && ok "claude,cursor,opencode 只装 ~/.claude/skills" || bad "min claude,cursor,opencode" "rc=$rc"
fresh; inst --host codex,codex,dsh; rc=$?
[ $rc = 0 ] && [ -f "$T/h/.agents/skills/hq/SKILL.md" ] && [ ! -e "$T/h/.dsh" ] && ok "codex,dsh 共用 ~/.agents/skills（重复宿主去重）" || bad "min codex,dsh" "rc=$rc"
# 各工具读到的副本数：每个登记宿主在 all 最小集合下 ≤ 2（opencode 同时读两处，会提示）
fresh; inst --host all; grep -q "注意: opencode 会从 2 个目录" "$T/out" && ! grep -q "注意: cursor" "$T/out" && ok "重复读取只对 opencode 提示" || bad "dup notice" "$(grep 注意 "$T/out")"

# 14. auto：按检测目录选宿主；HQ_NO_CMD_DETECT=1 屏蔽本机命令
fresh; mkdir -p "$T/h/.cursor" "$T/h/.gemini"
HOME="$T/h" HQ_NO_CMD_DETECT=1 bash "$INST" --host auto >"$T/out" 2>&1; rc=$?
[ $rc = 0 ] && [ -f "$T/h/.cursor/skills/hq/SKILL.md" ] && [ -f "$T/h/.gemini/skills/hq/SKILL.md" ] && [ ! -e "$T/h/.claude" ] && ok "auto 检测到 cursor、gemini 并安装" || bad "auto" "rc=$rc"
fresh; HOME="$T/h" HQ_NO_CMD_DETECT=1 bash "$INST" --host auto >"$T/out" 2>&1; rc=$?
[ $rc = 4 ] && [ -z "$(ls -A "$T/h")" ] && ok "auto 什么都没检测到 => 4 且不写入" || bad "auto none" "rc=$rc"

# 15. 安装记录与 skill-path
fresh; inst --host codex
grep -q '"version":"'"$(sed -n 's/^HQ_VERSION=//p' "$INST")"'"' "$T/h/.agents/skills/hq/.hq-install.json" 2>/dev/null && grep -q '"hosts":\["codex"\]' "$T/h/.agents/skills/hq/.hq-install.json" && ok "写入 .hq-install.json" || bad "marker" "$(cat "$T/h/.agents/skills/hq/.hq-install.json" 2>&1)"
[ "$(cat "$T/h/.hq/skill-path" 2>/dev/null)" = "$T/h/.agents/skills/hq" ] && ok "写入 ~/.hq/skill-path" || bad "skill-path" "$(cat "$T/h/.hq/skill-path" 2>&1)"
fresh; inst --host codex --scope project --project-dir "$T/p"
[ ! -e "$T/h/.hq" ] && ok "项目范围不写 ~/.hq" || bad "project skill-path" "written"

# 16. --list 不写入
fresh; mkdir -p "$T/h/.gemini"; HOME="$T/h" HQ_NO_CMD_DETECT=1 bash "$INST" --list >"$T/out" 2>&1; rc=$?
[ $rc = 0 ] && grep -q "✓ gemini" "$T/out" && grep -q "\.gemini/skills" "$T/out" && [ "$(find "$T/h" -type f | wc -l | tr -d ' ')" = 0 ] && ok "--list 显示检测和计划且不写入" || bad "--list" "rc=$rc"

# 17. --update：只更新有安装记录的副本
fresh; inst --host claude; inst --host codex
echo junk >"$T/h/.claude/skills/hq/junk"; sed -i.bak 's/"version":"[^"]*"/"version":"0.0.1"/' "$T/h/.claude/skills/hq/.hq-install.json"
rm -f "$T/h/.agents/skills/hq/.hq-install.json" "$T/h/.agents/skills/hq-retro/.hq-install.json"; echo old >"$T/h/.agents/skills/hq/old"
inst --update; rc=$?
[ $rc = 0 ] && [ ! -e "$T/h/.claude/skills/hq/junk" ] && grep -q "0.0.1 -> " "$T/out" && ! grep -q '0.0.1' "$T/h/.claude/skills/hq/.hq-install.json" && [ -f "$T/h/.agents/skills/hq/old" ] && grep -q "没有安装记录" "$T/out" && ok "--update 只更新有记录的副本" || bad "--update" "rc=$rc"

# 18. --uninstall：删有记录的，留无记录的；再次卸载 => 4
inst --uninstall; rc=$?
[ $rc = 0 ] && [ ! -e "$T/h/.claude/skills/hq" ] && [ -f "$T/h/.agents/skills/hq/old" ] && [ ! -e "$T/h/.hq/skill-path" ] && ok "--uninstall 只删有记录的副本" || bad "--uninstall" "rc=$rc"
inst --uninstall; rc=$?
[ $rc = 4 ] && ok "无可卸载副本 => 4" || bad "uninstall none" "rc=$rc"

# 19. 引导下载：脚本单独运行（无 skills/）时从 HQ_REPO_URL 克隆 HQ_REF 再安装
if command -v git >/dev/null 2>&1; then
  fresh; rm -rf "$T/src" "$T/boot" "$T/cache"; mkdir -p "$T/src" "$T/boot"
  (cd "$REPO" && tar cf - --exclude=.git .) | (cd "$T/src" && tar xf -)
  (cd "$T/src" && git init -q && git add -A && git -c user.email=t@t -c user.name=t commit -qm s && git tag v9.9.9) >/dev/null 2>&1
  cp "$INST" "$T/boot/install.sh"
  HOME="$T/h" HQ_REPO_URL="$T/src" HQ_REF=v9.9.9 HQ_CACHE_DIR="$T/cache" bash "$T/boot/install.sh" --host claude >"$T/out" 2>&1; rc=$?
  [ $rc = 0 ] && [ -f "$T/cache/v9.9.9/install.sh" ] && [ -f "$T/h/.claude/skills/hq/SKILL.md" ] && ok "引导下载后安装" || bad "bootstrap" "rc=$rc $(tail -2 "$T/out")"
  # 通过管道运行（curl | bash 的形态）
  fresh; HOME="$T/h" HQ_REPO_URL="$T/src" HQ_REF=v9.9.9 HQ_CACHE_DIR="$T/cache" bash -s -- --host codex <"$T/boot/install.sh" >"$T/out" 2>&1; rc=$?
  [ $rc = 0 ] && [ -f "$T/h/.agents/skills/hq/SKILL.md" ] && ok "管道运行（curl | bash）可用" || bad "bootstrap pipe" "rc=$rc $(tail -2 "$T/out")"
  fresh; HOME="$T/h" HQ_REPO_URL="$T/src" HQ_REF=v0.0.0-nope HQ_CACHE_DIR="$T/cache" bash "$T/boot/install.sh" --host claude >"$T/out" 2>&1; rc=$?
  [ $rc = 5 ] && [ ! -e "$T/h/.claude" ] && ok "下载失败 => 5 且不写入" || bad "bootstrap fail" "rc=$rc"
else
  echo "SKIP: 没有 git，跳过引导下载测试"
fi

# 20. 版本号一致：install.sh 与 plugin.json、marketplace.json
v=$(sed -n 's/^HQ_VERSION=//p' "$INST")
grep -q "\"version\": \"$v\"" "$REPO/.claude-plugin/plugin.json" && grep -q "\"version\": \"$v\"" "$REPO/.claude-plugin/marketplace.json" && grep -q "\"version\": \"$v\"" "$REPO/gemini-extension.json" && ok "版本号一致 ($v)" || bad "version" "install.sh=$v"

# 21. 登记表的每个宿主都有说明，读取目录都在 skill-dirs.tsv 里
okreg=1
while read -r id lv pr rd rest; do case "$id" in ''|\#*) continue;; esac
  for k in $(echo "$pr,$rd" | tr ',' ' '); do grep -Eq "^$k[[:space:]]" "$REPO/adapters/skill-dirs.tsv" || { okreg=0; echo "  $id: 未登记目录 $k"; }; done
  case "$lv" in native) [ -f "$REPO/skills/hq/references/hosts/$id.md" ] || [ "$id" = claude ] || { okreg=0; echo "  $id: 缺宿主文档"; };; basic) ;; *) okreg=0;; esac
done <"$REPO/adapters/hosts.tsv"
[ -f "$REPO/skills/hq/references/hosts/generic.md" ] || okreg=0
[ $okreg = 1 ] && ok "登记表自洽" || bad "registry" "见上"

# 22. 非法 --layout / 缺 --host
for args in "--host claude --layout x" "--force"; do
  fresh; inst $args; rc=$?
  [ $rc = 2 ] && ok "非法参数 '$args' 退出码 2" || bad "invalid '$args'" "rc=$rc"
done

# ---------- v0.4.1：模板生成器、--with-agents、OpenCode ----------
R="$REPO/adapters/render.sh"
# 23. 仓库里的模板与生成器输出一致（防止手改漂移）
bash "$R" --format codex --check "$REPO/adapters/codex/agents" >"$T/out" 2>&1 && ok "codex 模板与 tiers.tsv 一致" || bad "codex render check" "$(cat "$T/out")"
bash "$R" --format opencode --check "$REPO/adapters/opencode/agents" >"$T/out" 2>&1 && ok "opencode 模板与 tiers.tsv 一致" || bad "opencode render check" "$(cat "$T/out")"
# 24. opencode 模板是 V2 格式：mode: subagent，没有 V1 字段，默认不写 model
bad24=""
for f in "$REPO"/adapters/opencode/agents/hq-t*.md; do
  head -1 "$f" | grep -qx -- '---' || bad24="$bad24 $(basename "$f"):no-frontmatter"
  fm=$(awk 'NR==1{next} /^---$/{exit} {print}' "$f")
  echo "$fm" | grep -qx 'mode: subagent' || bad24="$bad24 $(basename "$f"):mode"
  echo "$fm" | grep -Eq '^(tools|permission|temperature|maxSteps|prompt|disable|name|model):' && bad24="$bad24 $(basename "$f"):v1-or-model"
done
[ -z "$bad24" ] && [ "$(ls "$REPO"/adapters/opencode/agents/hq-t*.md | wc -l | tr -d ' ')" = 5 ] && ok "opencode 模板为 V2 subagent 格式" || bad "opencode fmt" "$bad24"
# 25. --model-map：opencode 自动追加 #<思考深度>，显式 variant 保留；codex 填模型名
rm -rf "$T/r"; bash "$R" --format opencode --out "$T/r" --model-map 'T0=openai/m-small,T4=anthropic/m-big#max' >/dev/null 2>&1
grep -qx 'model: openai/m-small#low' "$T/r/hq-t0.md" && grep -qx 'model: anthropic/m-big#max' "$T/r/hq-t4.md" && ! grep -q '^model:' "$T/r/hq-t2.md" && ok "opencode --model-map 生成 provider/model#variant" || bad "opencode map" "$(grep -h model "$T/r"/*.md)"
rm -rf "$T/r"; bash "$R" --format codex --out "$T/r" --model-map 'T3=gpt-big' >/dev/null 2>&1
grep -qx 'model = "gpt-big"' "$T/r/hq-t3.toml" && grep -qx 'model_reasoning_effort = "medium"' "$T/r/hq-t3.toml" && grep -q '^model = "<' "$T/r/hq-t0.toml" && ok "codex --model-map 填模型、其余保留占位符" || bad "codex map" "-"
for m in 'T9=a/b' 'T0=' 'T0=nomodelslash' 'T0=a/b c'; do
  bash "$R" --format opencode --out "$T/r2" --model-map "$m" >/dev/null 2>&1; rc=$?
  [ $rc = 2 ] && ok "非法 --model-map '$m' 退出码 2" || bad "bad map '$m'" "rc=$rc"
done
# 26. install --with-agents：opencode 模板进 ~/.config/opencode/agents / <项目>/.opencode/agents
fresh; HOME="$T/h" bash "$INST" --host opencode --with-agents >"$T/out" 2>&1; rc=$?
[ $rc = 0 ] && [ "$(ls "$T/h/.config/opencode/agents"/hq-t*.md 2>/dev/null | wc -l | tr -d ' ')" = 5 ] && [ ! -e "$T/h/.codex" ] && grep -q "档位不生效" "$T/out" && ok "opencode --with-agents 个人范围" || bad "opencode agents user" "rc=$rc"
fresh; HOME="$T/h" bash "$INST" --host opencode --scope project --project-dir "$T/p" --with-agents --model-map 'T0=x/y,T1=x/y,T2=x/y,T3=x/z,T4=x/z' >"$T/out" 2>&1; rc=$?
[ $rc = 0 ] && grep -qx 'model: x/z#high' "$T/p/.opencode/agents/hq-t4.md" && [ ! -e "$T/h/.config/opencode/agents" ] && ok "opencode --with-agents --model-map 项目范围" || bad "opencode agents project" "rc=$rc $(tail -2 "$T/out")"
# 27. --with-agents 对多个宿主：codex + opencode 都装；对没有模板的宿主给提示
fresh; HOME="$T/h" bash "$INST" --host codex,opencode --with-agents >"$T/out" 2>&1; rc=$?
[ $rc = 0 ] && [ -f "$T/h/.codex/agents/hq-t2.toml" ] && [ -f "$T/h/.config/opencode/agents/hq-t2.md" ] && ok "codex,opencode --with-agents 两种模板都装" || bad "multi agents" "rc=$rc"
fresh; HOME="$T/h" bash "$INST" --host codex,opencode --with-agents --model-map 'T0=a/b' >"$T/out" 2>&1; rc=$?
[ $rc = 2 ] && [ -z "$(ls -A "$T/h")" ] && ok "--model-map 对应多个宿主 => 2 且不写入" || bad "map multi" "rc=$rc"
fresh; HOME="$T/h" bash "$INST" --host claude --with-agents >"$T/out" 2>&1; rc=$?
[ $rc = 0 ] && grep -q "没有子代理模板" "$T/out" && [ ! -e "$T/h/.codex" ] && ok "claude --with-agents 提示无模板" || bad "claude agents" "rc=$rc"
# 28. opencode 模板已存在 => 3 且不装一半；OPENCODE_AGENTS_DIR 覆盖
fresh; mkdir -p "$T/ag"; echo keep >"$T/ag/hq-t1.md"
HOME="$T/h" OPENCODE_AGENTS_DIR="$T/ag" bash "$INST" --host opencode --with-agents >"$T/out" 2>&1; rc=$?
[ $rc = 3 ] && grep -q keep "$T/ag/hq-t1.md" && [ ! -e "$T/h/.config/opencode/skills/hq" ] && ok "opencode 模板已存在 => 3 且不装一半" || bad "opencode agents exists" "rc=$rc"
# 29. dry-run + model-map 不写入
fresh; HOME="$T/h" bash "$INST" --host opencode --with-agents --model-map 'T0=a/b' --dry-run >"$T/out" 2>&1; rc=$?
[ $rc = 0 ] && [ -z "$(find "$T/h" -type f)" ] && ok "dry-run + --model-map 不写入" || bad "dry map" "rc=$rc"

# ---------- v0.4.3：Gemini 扩展与 Gemini 子代理 ----------
# 30. 扩展清单与目录结构
python3 - "$REPO" >"$T/out" 2>&1 <<'PY2'
import json,sys,os,tomllib
r=sys.argv[1]; errs=[]
m=json.load(open(os.path.join(r,"gemini-extension.json")))
if m.get("name")!="hq-orchestrator": errs.append("name")
if not m.get("description"): errs.append("description")
if "contextFileName" in m: errs.append("contextFileName 会把文件注入每个会话")
if os.path.exists(os.path.join(r,"GEMINI.md")): errs.append("根目录不应有 GEMINI.md（会自动注入上下文）")
if os.path.isdir(os.path.join(r,"agents")): errs.append("根目录不应有 agents/（Claude Code 插件会加载）")
for s in ("hq","hq-retro"):
    if not os.path.isfile(os.path.join(r,"skills",s,"SKILL.md")): errs.append("skills/"+s)
for c,skill in (("hq","hq"),("hq-retro","hq-retro")):
    t=tomllib.load(open(os.path.join(r,"commands",c+".toml"),"rb"))
    if not t.get("description") or "{{args}}" not in t.get("prompt","") or ("技能名 "+skill) not in t["prompt"]: errs.append("commands/"+c)
if [f for f in os.listdir(os.path.join(r,"commands")) if not f.endswith(".toml")]: errs.append("commands/ 只放 .toml")
print("\n".join(errs)); sys.exit(1 if errs else 0)
PY2
[ $? = 0 ] && ok "Gemini 扩展清单、技能、命令结构正确" || bad "gemini extension" "$(cat "$T/out")"
# 31. gemini 模板：与生成器一致；name 与文件名一致、kind local、默认不写 model
bash "$R" --format gemini --check "$REPO/adapters/gemini/agents" >"$T/out" 2>&1 && ok "gemini 模板与 tiers.tsv 一致" || bad "gemini render check" "$(cat "$T/out")"
bad31=""
for f in "$REPO"/adapters/gemini/agents/hq-t*.md; do
  fm=$(awk 'NR==1{next} /^---$/{exit} {print}' "$f"); n=$(basename "$f" .md)
  echo "$fm" | grep -qx "name: $n" || bad31="$bad31 $n:name"
  echo "$fm" | grep -qx 'kind: local' || bad31="$bad31 $n:kind"
  echo "$fm" | grep -q '^model:' && bad31="$bad31 $n:model"
  echo "$fm" | grep -qx 'timeout_mins: 60' || bad31="$bad31 $n:timeout"
done
[ -z "$bad31" ] && ok "gemini 模板格式（name/kind/timeout，默认无 model）" || bad "gemini fmt" "$bad31"
rm -rf "$T/r"; bash "$R" --format gemini --out "$T/r" --model-map 'T0=g-small,T4=g-pro' >/dev/null 2>&1
grep -qx 'model: g-small' "$T/r/hq-t0.md" && grep -qx 'model: g-pro' "$T/r/hq-t4.md" && ! grep -q '^model:' "$T/r/hq-t2.md" && ok "gemini --model-map 填模型名" || bad "gemini map" "$(grep -h '^model' "$T/r"/*.md)"
# 32. install --host gemini --with-agents；已装扩展时提示
fresh; HOME="$T/h" bash "$INST" --host gemini --with-agents --model-map 'T0=a,T1=b,T2=b,T3=c,T4=c' >"$T/out" 2>&1; rc=$?
[ $rc = 0 ] && [ "$(ls "$T/h/.gemini/agents"/hq-t*.md 2>/dev/null | wc -l | tr -d ' ')" = 5 ] && grep -qx 'model: c' "$T/h/.gemini/agents/hq-t3.md" && [ -f "$T/h/.gemini/skills/hq/SKILL.md" ] && ok "gemini --with-agents 装到 ~/.gemini/agents" || bad "gemini agents" "rc=$rc $(tail -2 "$T/out")"
fresh; mkdir -p "$T/h/.gemini/extensions/hq-orchestrator"; HOME="$T/h" bash "$INST" --host gemini >"$T/out" 2>&1; rc=$?
[ $rc = 0 ] && grep -q "已装 Gemini 扩展" "$T/out" && ok "已装 Gemini 扩展时提示重复" || bad "gemini ext notice" "rc=$rc"
fresh; HOME="$T/h" bash "$INST" --host gemini >"$T/out" 2>&1
! grep -q "已装 Gemini 扩展" "$T/out" && ok "未装扩展时不提示" || bad "gemini ext no notice" "-"

# 33. macOS 自带 bash 3.2 在 UTF-8 locale 下会把非 ASCII 字节当成变量名的一部分（如 $ 后跟 s 再跟全角括号，会被读成变量 s\xEF…，set -u 下报 unbound variable）；
#     所以紧跟非 ASCII 字符的变量必须写成 ${var}
ROOTD="$(dirname "$INST")"
hits=$(cd "$ROOTD" && find install.sh adapters skills tests -name '*.sh' -exec perl -ne 'print "$ARGV:$.: $_" if /(?<!\\)\$[A-Za-z_][A-Za-z0-9_]*[^\x00-\x7F]/; close ARGV if eof' {} +)
[ -z "$hits" ] && ok "紧跟非 ASCII 的变量都带花括号（兼容 bash 3.2）" || bad "bash 3.2 多字节变量名" "$hits"

echo "----"
echo "SUMMARY: $pass passed, $fail failed"
[ $fail -eq 0 ]
