#!/usr/bin/env bash
# 由 adapters/tiers.tsv 生成各宿主的 hq-t0…hq-t4 子代理模板。兼容 bash 3.2。
#   render.sh --format codex|opencode|gemini --out <目录> [--model-map 'T0=<模型>,T3=<模型>']
#   render.sh --format codex|opencode|gemini --check <目录>     与目录里的文件比较，不一致退出 1
#   render.sh --all                                      重新生成 adapters/<格式>/agents/（仓库维护用）
# --model-map 的值：codex、gemini 为模型名；opencode 为 provider/model，可带 #variant（不带时按档位追加 #<思考深度>）。
# 没填的档位保留占位：codex 写占位符（必须替换），opencode、gemini 不写 model（继承父会话模型）。
# 退出码: 0 成功; 1 --check 不一致; 2 参数非法
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FORMATS="codex opencode gemini"

die2() { echo "错误: $1" >&2; sed -n '2,8p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2; exit 2; }

fmt=""; out=""; check=""; map=""; all=0
while [ $# -gt 0 ]; do
  case "$1" in
    --format) [ $# -ge 2 ] || die2 "--format 缺少值"; fmt=$2; shift 2;;
    --out) [ $# -ge 2 ] || die2 "--out 缺少值"; out=$2; shift 2;;
    --check) [ $# -ge 2 ] || die2 "--check 缺少值"; check=$2; shift 2;;
    --model-map) [ $# -ge 2 ] || die2 "--model-map 缺少值"; map=$2; shift 2;;
    --all) all=1; shift;;
    -h|--help) sed -n '2,8p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0;;
    *) die2 "未知参数: $1";;
  esac
done

if [ $all = 1 ]; then
  for f in $FORMATS; do
    mkdir -p "$HERE/$f/agents"
    rm -f "$HERE/$f/agents"/hq-t*.*
    bash "${BASH_SOURCE[0]}" --format "$f" --out "$HERE/$f/agents" || exit $?
  done
  exit 0
fi
case " $FORMATS " in *" $fmt "*) ;; *) die2 "--format 必须是 ${FORMATS// /|}";; esac
[ -n "$out" ] || [ -n "$check" ] || die2 "需要 --out 或 --check"
[ -f "$HERE/tiers.tsv" ] || die2 "缺少 $HERE/tiers.tsv"

# 解析 --model-map 为 M_T0..M_T4
M_T0=""; M_T1=""; M_T2=""; M_T3=""; M_T4=""
if [ -n "$map" ]; then
  IFS=, read -r -a pairs <<<"$map"
  for kv in "${pairs[@]}"; do
    [ -n "$kv" ] || continue
    k=${kv%%=*}; v=${kv#*=}
    case "$k" in T0|T1|T2|T3|T4) ;; *) die2 "--model-map 的键必须是 T0–T4: $kv";; esac
    [ "$kv" != "$k" ] && [ -n "$v" ] || die2 "--model-map 缺少模型: $kv"
    case "$v" in *[[:space:]\"\\]*) die2 "--model-map 的模型名不能含空白、引号或反斜杠: $v";; esac
    if [ "$fmt" = opencode ]; then
      case "$v" in */*) ;; *) die2 "opencode 的模型要写成 provider/model[#variant]: $v";; esac
    fi
    eval "M_$k=\$v"
  done
fi

ext=toml; [ "$fmt" != codex ] && ext=md
dst=$out
if [ -n "$check" ]; then dst=$(mktemp -d); trap 'rm -rf "$dst"' EXIT; fi
mkdir -p "$dst"

body() {  # $1=档位
  cat <<B
你是 hq-orchestrator 派发的子代理（档位 $1）。严格按任务说明（brief）工作：只改说明允许的范围，先跑说明规定的验证。
交付时用以下固定格式作为最后一条消息，没有内容的项写 none：
STATUS / BRANCH / CHANGES / VERIFY / CHECKPOINTS / DERIVED / RISKS / QUESTIONS
B
}

while read -r tier effort cls desc; do
  case "$tier" in ''|\#*) continue;; esac
  lo=$(printf '%s' "$tier" | tr 'T' 't'); name="hq-$lo"
  eval "m=\$M_$tier"
  f="$dst/$name.$ext"
  if [ "$fmt" = codex ]; then
    {
      echo "# 由 adapters/render.sh 从 adapters/tiers.tsv 生成，请改 tiers.tsv 后重新生成，不要手改。"
      echo "# 已按官方文档核对（2026-11-25），未实机运行：必填 name / description / developer_instructions，"
      echo "# 可选 model / model_reasoning_effort；放在 ~/.codex/agents/（个人）或 <项目>/.codex/agents/（项目）。"
      echo "# sandbox_mode / approval_policy 等写在这里不会覆盖父会话，不要依赖。"
      echo "name = \"$name\""
      echo "description = \"HQ 档位 ${tier}：适合$desc\""
      if [ -n "$m" ]; then
        echo "model = \"$m\""
      else
        echo "# ${cls}：占位符，必须替换成你账户里 \`codex\` 实际可用的模型名（见 adapters/codex/README.md），不要原样使用。"
        echo "model = \"<$cls>\""
      fi
      echo "model_reasoning_effort = \"$effort\""
      echo 'developer_instructions = """'
      body "$tier"
      echo '"""'
    } >"$f"
  elif [ "$fmt" = gemini ]; then
    {
      echo "---"
      echo "# 由 adapters/render.sh 从 adapters/tiers.tsv 生成，请改 tiers.tsv 后重新生成，不要手改。"
      echo "# Gemini CLI 子代理格式（官方文档 docs/core/subagents.md，2026-11-24，未实机运行）；放在 ~/.gemini/agents/ 或 <项目>/.gemini/agents/。"
      echo "# 命令行和子代理都没有思考深度设置，档位只靠模型区分（本档原定思考深度 ${effort}）。"
      echo "name: $name"
      echo "description: \"HQ 档位 ${tier}（${cls}）：适合${desc}由 hq 技能按档位派发。\""
      echo "kind: local"
      if [ -n "$m" ]; then
        echo "model: $m"
      else
        echo "# 未设置 model：继承主会话模型，档位不生效。填法见 adapters/gemini/README.md，例如："
        echo "# model: <$cls>"
      fi
      echo "# 默认 30 轮、10 分钟太短，改代码的任务放宽"
      echo "max_turns: 100"
      echo "timeout_mins: 60"
      echo "---"
      echo
      body "$tier"
      echo "工作目录：任务说明写了 worktree 路径时，所有读写和命令都只在该目录内进行（命令先 cd 进去），不要改动主工作区。"
    } >"$f"
  else
    {
      echo "---"
      echo "# 由 adapters/render.sh 从 adapters/tiers.tsv 生成，请改 tiers.tsv 后重新生成，不要手改。"
      echo "# OpenCode V2 agent 格式（官方文档 2026-11-25，未实机运行）；放在 ~/.config/opencode/agents/ 或 <项目>/.opencode/agents/。"
      echo "description: \"HQ 档位 ${tier}（${cls}，思考深度 ${effort}）：适合${desc}由 hq 技能按档位派发。\""
      echo "mode: subagent"
      if [ -n "$m" ]; then
        case "$m" in *#*) ;; *) m="$m#$effort";; esac
        echo "model: $m"
      else
        echo "# 未设置 model：继承父会话的模型，档位不生效。填法见 adapters/opencode/README.md，例如："
        echo "# model: <provider>/<$cls>#$effort"
      fi
      echo "---"
      echo
      body "$tier"
      echo "工作目录：任务说明写了 worktree 路径时，所有读写和命令都只在该目录内进行（命令先 cd 进去），不要改动主工作区。"
    } >"$f"
  fi
done <"$HERE/tiers.tsv"

if [ -n "$check" ]; then
  rc=0
  for f in "$dst"/*."$ext"; do
    g="$check/$(basename "$f")"
    if ! cmp -s "$f" "$g"; then echo "不一致: ${g}（运行 adapters/render.sh --all 重新生成）" >&2; rc=1; fi
  done
  for g in "$check"/hq-t*."$ext"; do
    [ -e "$g" ] || continue
    [ -e "$dst/$(basename "$g")" ] || { echo "多余文件: $g" >&2; rc=1; }
  done
  exit $rc
fi
exit 0
