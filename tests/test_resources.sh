#!/usr/bin/env bash
# resources.sh 自测：用 HQ_FAKE_* 注入读数覆盖各分级分支。
SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/skills/hq/scripts/resources.sh"
pass=0; fail=0

ok()  { echo "PASS: $1"; pass=$((pass+1)); }
bad() { echo "FAIL: $1 ($2)"; fail=$((fail+1)); }

jget() { python3 -c 'import json,sys; print(json.loads(sys.argv[1])[sys.argv[2]])' "$1" "$2"; }

# run_case 名称 期望level 期望slots 参数... -- 环境变量(K=V)...
run_case() {
  local name=$1 want_level=$2 want_slots=$3; shift 3
  local args=() envs=()
  while [ $# -gt 0 ] && [ "$1" != "--" ]; do args+=("$1"); shift; done
  shift
  envs=("$@")
  local out lv sl
  out=$(env "${envs[@]}" bash "$SCRIPT" "${args[@]}" 2>&1)
  lv=$(jget "$out" level 2>/dev/null); sl=$(jget "$out" new_local_slots 2>/dev/null)
  if [ "$lv" = "$want_level" ] && [ "$sl" = "$want_slots" ]; then ok "$name"
  else bad "$name" "want $want_level/$want_slots got $lv/$sl: $out"; fi
}

# 基线 GREEN 读数: 8核 load1=1 总16000 可用12000 无swap 磁盘50000
G=(HQ_FAKE_CORES=8 HQ_FAKE_LOAD1=1 HQ_FAKE_MEM_TOTAL_MB=16000 HQ_FAKE_MEM_AVAIL_MB=12000
   HQ_FAKE_SWAP_TOTAL_MB=0 HQ_FAKE_SWAP_USED_MB=0 HQ_FAKE_DISK_FREE_MB=50000)
# over 数组名 KEY=VAL...: 基线并覆盖，结果写入数组（不用 local -n，兼容 macOS 自带的 bash 3.2）
over() {
  local _name=$1; shift
  local -a _r=("${G[@]}")
  local kv k i found
  for kv in "$@"; do k=${kv%%=*}; found=0
    for i in "${!_r[@]}"; do [ "${_r[$i]%%=*}" = "$k" ] && { _r[$i]=$kv; found=1; }; done
    [ $found = 1 ] || _r+=("$kv")
  done
  eval "$_name=(\"\${_r[@]}\")"
}

# 1. 真实运行输出合法 JSON 且字段齐全
out=$(env -u HQ_FAKE_CORES -u HQ_FAKE_LOAD1 -u HQ_FAKE_MEM_TOTAL_MB -u HQ_FAKE_MEM_AVAIL_MB \
  -u HQ_FAKE_SWAP_TOTAL_MB -u HQ_FAKE_SWAP_USED_MB -u HQ_FAKE_DISK_FREE_MB -u HQ_FAKE_UNREADABLE bash "$SCRIPT" 2>&1)
if python3 -c '
import json,sys
d=json.loads(sys.argv[1])
need="os cores load1 mem_total_mb mem_avail_mb mem_avail_pct swap_used_pct disk_free_mb level new_local_slots reason unreadable".split()
miss=[k for k in need if k not in d]
assert not miss, miss
assert d["level"] in ("GREEN","YELLOW","RED","UNKNOWN")
assert isinstance(d["unreadable"], list)
' "$out" 2>/dev/null; then ok "real run: valid JSON with all fields"
else bad "real run: valid JSON with all fields" "$out"; fi

# 2. GREEN: reserve=max(1024,2400)=2400; mem=int(9600/1500)=6; cpu=int((6.4-1)/1)=5 -> 5
run_case "GREEN slots=5 (cpu-bound)" GREEN 5 1500 1 6 -- "${G[@]}"
# 3. 硬上限
run_case "hard cap=2 applies" GREEN 2 1500 1 2 -- "${G[@]}"
over e HQ_FAKE_MEM_AVAIL_MB=6000   # mem=int(3600/1500)=2, 37.5% 仍 GREEN
run_case "GREEN memory-bound slots=2" GREEN 2 1500 1 6 -- "${e[@]}"

# 4. YELLOW 时 slots<=1
# 内存触发: 可用 3900(24.4%<25%, >10%); 轻任务 400/0.25: mem=int(1500/400)=3, cpu=int(5.4/.25)=21 -> 3 -> 限制为 1
over e HQ_FAKE_MEM_AVAIL_MB=3900
run_case "YELLOW by memory, slots capped to 1" YELLOW 1 400 0.25 6 -- "${e[@]}"
# CPU 触发: 16核 load1=14.5 (>14.4, <24); 可用内存充足; cpu_free=12.8-14.5<0 -> 0
over e HQ_FAKE_CORES=16 HQ_FAKE_LOAD1=14.5
run_case "YELLOW by cpu load, slots<=1" YELLOW 0 1500 1 6 -- "${e[@]}"
# 磁盘触发(其余充足, 未截断前为5): 验证上限截断到 1
over e HQ_FAKE_DISK_FREE_MB=1500
run_case "YELLOW by disk, slots capped to 1" YELLOW 1 1500 1 6 -- "${e[@]}"

# 5. RED 四种触发
over e HQ_FAKE_MEM_AVAIL_MB=1200
run_case "RED by memory <10%" RED 0 1500 1 6 -- "${e[@]}"
over e HQ_FAKE_LOAD1=13
run_case "RED by load1 > cores*1.5" RED 0 1500 1 6 -- "${e[@]}"
over e HQ_FAKE_SWAP_TOTAL_MB=4000 HQ_FAKE_SWAP_USED_MB=2500
run_case "RED by swap >50%" RED 0 1500 1 6 -- "${e[@]}"
over e HQ_FAKE_DISK_FREE_MB=300
run_case "RED by disk <512MB" RED 0 1500 1 6 -- "${e[@]}"

# 5b. 读不到读数（沙箱禁止 sysctl 等）：不当成 0，记 UNKNOWN，最多 1 个槽位；已读到的读数显示 RED 时仍为 RED
over e HQ_FAKE_UNREADABLE=cores,load1,mem_total
run_case "UNKNOWN when cpu/mem unreadable, slots capped to 1" UNKNOWN 1 1500 1 6 -- "${e[@]}"
over e HQ_FAKE_UNREADABLE=disk_free
run_case "UNKNOWN when only disk unreadable" UNKNOWN 1 1500 1 6 -- "${e[@]}"
over e HQ_FAKE_UNREADABLE=cores HQ_FAKE_CORES=8 HQ_FAKE_MEM_AVAIL_MB=6000
run_case "UNKNOWN caps memory-bound slots (2 -> 1)" UNKNOWN 1 1500 1 6 -- "${e[@]}"
over e HQ_FAKE_UNREADABLE=cores,load1 HQ_FAKE_MEM_AVAIL_MB=1200
run_case "RED from readable mem wins over UNKNOWN" RED 0 1500 1 6 -- "${e[@]}"
over e HQ_FAKE_UNREADABLE=mem_total,mem_avail HQ_FAKE_DISK_FREE_MB=300
run_case "RED from readable disk wins over UNKNOWN" RED 0 1500 1 6 -- "${e[@]}"
over e HQ_FAKE_UNREADABLE=cores,mem_avail,swap
out=$(env "${e[@]}" bash "$SCRIPT" 1500 1 6 2>&1)
python3 -c '
import json,sys
d=json.loads(sys.argv[1])
assert d["cores"] is None and d["mem_avail_mb"] is None and d["mem_avail_pct"] is None and d["swap_used_pct"] is None, d
assert d["load1"] is not None and d["mem_total_mb"] == 16000, d
assert d["unreadable"] == ["cores","mem_avail","swap"], d
assert "无法读取" in d["reason"], d
' "$out" 2>/dev/null && ok "unreadable fields are null and listed" || bad "unreadable fields null" "$out"
# 真实不可读：没有 sysctl/vm_stat/proc 的 PATH 下（只留 awk/df 等），macOS 也不能报出 0 当 RED
d=$(mktemp -d); for c in awk df uname tr cut cat; do p=$(command -v $c) && ln -s "$p" "$d/$c"; done
out=$(env -i PATH="$d" HOME="$HOME" /bin/bash "$SCRIPT" 1500 1 6 2>&1); rm -rf "$d"
lv=$(jget "$out" level 2>/dev/null)
if [ "$(uname -s)" = Darwin ]; then [ "$lv" = UNKNOWN ] && ok "darwin without sysctl/vm_stat -> UNKNOWN" || bad "darwin without sysctl" "$out"
else ok "darwin without sysctl/vm_stat (skipped: not Darwin)"; fi

# 6. 非法参数退出码 2
check_bad() {
  local name=$1; shift
  bash "$SCRIPT" "$@" >/dev/null 2>&1; local rc=$?
  if [ $rc -eq 2 ]; then ok "invalid args exit 2: $name"; else bad "invalid args exit 2: $name" "rc=$rc"; fi
}
check_bad "negative mem" -5 1 6
check_bad "non-numeric mem" abc 1 6
check_bad "non-numeric cpu" 1500 x 6
check_bad "negative cap" 1500 1 -1
check_bad "decimal cap" 1500 1 2.5
check_bad "too many args" 1 1 1 1
check_bad "zero mem" 0 1 6
if bash "$SCRIPT" 400 0.25 6 >/dev/null 2>&1; then ok "decimal cpu accepted"; else bad "decimal cpu accepted" "rejected"; fi

echo "----"
echo "SUMMARY: $pass passed, $fail failed"
[ $fail -eq 0 ]
