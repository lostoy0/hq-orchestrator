# gemini 后端：Gemini CLI 无界面模式。依据 google-gemini/gemini-cli 的 docs/cli/headless.md、docs/cli/cli-reference.md
# 和 packages/core/src/output/types.ts（2026-11-24），未实机运行：
#   - -p 的文本追加在 stdin 之后，所以简报经 stdin 传入、-p 只放一句执行指令；-m 选模型；
#   - --output-format stream-json 的最后一个 result 事件带 stats：input_tokens（含 cached）、output_tokens、cached；
#   - --approval-mode default|auto_edit|yolo|plan；命令行没有思考深度参数。
be_argv() {
  argv=(gemini -m "$MODEL" --output-format stream-json)
  case $SANDBOX in
    read-only) argv+=(--approval-mode plan);;
    workspace-write) argv+=(--approval-mode auto_edit)
      NOTES="${NOTES}gemini auto_edit 只自动批准编辑，shell 命令（如跑测试）可能不可用，验证需由主会话补做；";;
    danger-full-access) argv+=(--approval-mode yolo);;
  esac
  argv+=(-p "按上面的任务说明执行，完成后按说明里的交付格式回复。")
  [ -n "$EFFORT" ] && NOTES="${NOTES}gemini 命令行不支持思考深度，忽略 --effort ${EFFORT}；"
  STDIN_SRC=brief
}
be_usage() {
  python3 - "$1" <<'PY'
import sys,json
def n(x): return x if isinstance(x,(int,float)) and not isinstance(x,bool) else None
tokens=None; source=None
for line in open(sys.argv[1],encoding="utf-8",errors="replace"):
    try: o=json.loads(line)
    except Exception: continue
    if not isinstance(o,dict): continue
    st=o.get("stats") if o.get("type")=="result" else None
    if isinstance(st,dict):
        i=n(st.get("input_tokens")); out=n(st.get("output_tokens")); cr=n(st.get("cached")) or 0
        if i is not None or out is not None:
            # input_tokens 含缓存读取（cached），按口径扣除；没有 cache_write 概念
            tokens=int(max((i or 0)-cr,0)+(out or 0)); source="gemini:result.stats"
print(json.dumps({"tokens":tokens,"cost_usd":None,"source":source}))
PY
}
