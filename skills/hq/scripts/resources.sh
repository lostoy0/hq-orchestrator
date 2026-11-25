#!/usr/bin/env bash
# HQ 资源探测：输出一行 JSON，告诉总指挥"现在还能再开几个本地重任务"。
# 用法: resources.sh [每任务内存MB=1500] [每任务CPU核=1] [硬上限=6]
#   重任务(构建/测试/跑服务): 1500 1
#   轻任务(只读写代码、不跑重命令): 400 0.25
# 支持 Linux(含 cgroup v2 容器限制) 与 macOS。只读，不改动系统。
# 参数必须是非负数(核数可为小数，每任务内存为正整数，硬上限为整数)，否则向 stderr 报用法并以退出码 2 退出。
# 测试用模拟读数(设置后覆盖真实测量值，不设置则行为不变):
#   HQ_FAKE_CORES HQ_FAKE_LOAD1 HQ_FAKE_MEM_TOTAL_MB HQ_FAKE_MEM_AVAIL_MB
#   HQ_FAKE_SWAP_TOTAL_MB HQ_FAKE_SWAP_USED_MB HQ_FAKE_DISK_FREE_MB
#   HQ_FAKE_UNREADABLE=cores,load1,mem_total,mem_avail,swap,disk_free（逗号分隔，模拟这些读数读不到）
# 读不到的读数（沙箱禁止 sysctl、/proc 不可读等）不会当成 0：输出里记为 null、列进 unreadable，
# level 为 UNKNOWN，new_local_slots 最多 1（已读到的读数显示 RED 时仍为 RED）。
set -u
PER_MEM=${1:-1500}
PER_CPU=${2:-1}
CAP=${3:-6}

usage() {
  echo "用法: resources.sh [每任务内存MB(正整数)=1500] [每任务CPU核(非负数,可小数)=1] [硬上限(非负整数)=6]" >&2
  exit 2
}
[ $# -le 3 ] || usage
[[ $PER_MEM =~ ^[1-9][0-9]*$ ]] || usage
[[ $PER_CPU =~ ^[0-9]+(\.[0-9]+)?$ || $PER_CPU =~ ^\.[0-9]+$ ]] || usage
[[ $CAP =~ ^[0-9]+$ ]] || usage

os=$(uname -s)
cores=""; load1=""; mem_total=""; mem_avail=""; swap_total=0; swap_used=0

if [ "$os" = "Linux" ]; then
  cores=$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1)
  if [ -r /sys/fs/cgroup/cpu.max ]; then
    read -r q p < /sys/fs/cgroup/cpu.max
    if [ "$q" != "max" ] && [ -n "${p:-}" ] && [ "$p" -gt 0 ]; then
      c=$(( (q + p - 1) / p )); [ "$c" -lt "$cores" ] && [ "$c" -gt 0 ] && cores=$c
    fi
  fi
  load1=$(cut -d' ' -f1 /proc/loadavg 2>/dev/null)
  mem_total=$(awk '/^MemTotal:/{print int($2/1024)}' /proc/meminfo 2>/dev/null)
  mem_avail=$(awk '/^MemAvailable:/{print int($2/1024)}' /proc/meminfo 2>/dev/null)
  swap_total=$(awk '/^SwapTotal:/{print int($2/1024)}' /proc/meminfo 2>/dev/null)
  swap_used=$(awk '/^SwapTotal:/{t=$2}/^SwapFree:/{f=$2}END{if(t!="")print int((t-f)/1024)}' /proc/meminfo 2>/dev/null)
  # cgroup v2 内存上限（容器/云端会话里比 /proc/meminfo 更真实）
  if [ -r /sys/fs/cgroup/memory.max ]; then
    lim=$(cat /sys/fs/cgroup/memory.max)
    if [ "$lim" != "max" ]; then
      lim_mb=$(( lim / 1048576 ))
      cur=$(cat /sys/fs/cgroup/memory.current 2>/dev/null || echo 0)
      inact=$(awk '/^inactive_file /{print $2}' /sys/fs/cgroup/memory.stat 2>/dev/null || echo 0)
      used_mb=$(( (cur - ${inact:-0}) / 1048576 ))
      if [[ $mem_total =~ ^[0-9]+$ ]] && [ "$lim_mb" -lt "$mem_total" ]; then
        mem_total=$lim_mb
        a=$(( lim_mb - used_mb )); { ! [[ $mem_avail =~ ^[0-9]+$ ]] || [ "$a" -lt "$mem_avail" ]; } && mem_avail=$a
      fi
    fi
  fi
elif [ "$os" = "Darwin" ]; then
  # 沙箱（如 Codex workspace-write）可能禁止 sysctl：读不到就留空，不当成 0
  cores=$(sysctl -n hw.ncpu 2>/dev/null)
  load1=$(sysctl -n vm.loadavg 2>/dev/null | awk '{print $2}')
  mb=$(sysctl -n hw.memsize 2>/dev/null); [[ $mb =~ ^[0-9]+$ ]] && mem_total=$(( mb / 1048576 ))
  mem_avail=$(vm_stat 2>/dev/null | awk '
    /page size of/ {ps=$8}
    /Pages free/ {f=$3} /Pages inactive/ {i=$3} /Pages speculative/ {s=$3} /Pages purgeable/ {p=$3}
    END {if (ps=="" || f=="") exit; gsub(/\./,"",f);gsub(/\./,"",i);gsub(/\./,"",s);gsub(/\./,"",p); print int((f+i+s+p)*ps/1048576)}')
  sw=$(sysctl -n vm.swapusage 2>/dev/null)
  swap_total=$(echo "$sw" | awk '{for(i=1;i<=NF;i++) if($i=="total"){v=$(i+2); sub(/M/,"",v); print int(v)}}')
  swap_used=$(echo "$sw" | awk '{for(i=1;i<=NF;i++) if($i=="used"){v=$(i+2); sub(/M/,"",v); print int(v)}}')
fi

disk_free=$(df -Pk . 2>/dev/null | awk 'NR==2{print int($4/1024)}')

# 模拟读数覆盖(仅测试用)
cores=${HQ_FAKE_CORES:-$cores}
load1=${HQ_FAKE_LOAD1:-$load1}
mem_total=${HQ_FAKE_MEM_TOTAL_MB:-$mem_total}
mem_avail=${HQ_FAKE_MEM_AVAIL_MB:-$mem_avail}
swap_total=${HQ_FAKE_SWAP_TOTAL_MB:-$swap_total}
swap_used=${HQ_FAKE_SWAP_USED_MB:-$swap_used}
disk_free=${HQ_FAKE_DISK_FREE_MB:-$disk_free}
for k in $(echo "${HQ_FAKE_UNREADABLE:-}" | tr ',' ' '); do
  case $k in cores|load1|mem_total|mem_avail|disk_free) eval "$k=''";; swap) swap_total="";; esac
done

# 读不到（空或非数字；核数、总内存为 0 也算）的读数列进 unreadable
isnum() { [[ $1 =~ ^[0-9]+(\.[0-9]+)?$ ]]; }
unreadable=""
isnum "$cores" && [ "${cores%%.*}" -gt 0 ] || { unreadable="${unreadable}cores,"; cores=0; }
isnum "$load1" || { unreadable="${unreadable}load1,"; load1=0; }
isnum "$mem_total" && [ "${mem_total%%.*}" -gt 0 ] || { unreadable="${unreadable}mem_total,"; mem_total=0; }
isnum "$mem_avail" || { unreadable="${unreadable}mem_avail,"; mem_avail=0; }
isnum "$disk_free" || { unreadable="${unreadable}disk_free,"; disk_free=0; }
isnum "${swap_total:-}" || { unreadable="${unreadable}swap,"; swap_total=0; }
isnum "${swap_used:-}" || swap_used=0
unreadable=${unreadable%,}

awk -v cores="$cores" -v load1="$load1" -v mt="$mem_total" -v ma="$mem_avail" \
    -v st="${swap_total:-0}" -v su="${swap_used:-0}" -v disk="${disk_free:-0}" \
    -v pm="$PER_MEM" -v pc="$PER_CPU" -v cap="$CAP" -v os="$os" -v ur="$unreadable" 'BEGIN {
  n = split(ur, a, ","); for (i = 1; i <= n; i++) U[a[i]] = 1
  cpu_ok = !(("cores" in U) || ("load1" in U)); mem_ok = !(("mem_total" in U) || ("mem_avail" in U)); disk_ok = !("disk_free" in U)
  reserve = mt * 0.15; if (reserve < 1024) reserve = 1024          # 给系统和主会话留余量
  mem_slots = cap; if (mem_ok) { mem_slots = int((ma - reserve) / pm); if (mem_slots < 0) mem_slots = 0 }
  cpu_slots = cap; if (cpu_ok) { cpu_free = cores * 0.8 - load1
    cpu_slots = (pc > 0) ? int(cpu_free / pc) : cap; if (cpu_slots < 0) cpu_slots = 0 }
  slots = mem_slots; if (cpu_slots < slots) slots = cpu_slots; if (cap < slots) slots = cap
  swap_pct = (st > 0) ? su * 100 / st : 0
  mem_pct = (mem_ok && mt > 0) ? ma * 100 / mt : 100
  level = "GREEN"; why = ""
  if (mem_pct < 25 || (cpu_ok && load1 > cores * 0.9) || (disk_ok && disk < 2048)) { level = "YELLOW" }
  if (mem_pct < 10 || (cpu_ok && load1 > cores * 1.5) || swap_pct > 50 || (disk_ok && disk < 512)) { level = "RED"; slots = 0 }
  if (level == "YELLOW" && slots > 1) slots = 1
  if (mem_pct < 25) why = why "内存紧张;"
  if (cpu_ok && load1 > cores * 0.9) why = why "CPU负载高;"
  if (swap_pct > 50) why = why "大量使用交换区;"
  if (disk_ok && disk < 2048) why = why "磁盘余量低;"
  # 读不到的维度不能当成 0：已读到的读数没到 RED 时记 UNKNOWN，保守地最多再开 1 个
  if (n > 0 && level != "RED") { level = "UNKNOWN"; if (slots > 1) slots = 1 }
  if (n > 0) why = why "无法读取:" ur ";"
  q = ""; for (i = 1; i <= n; i++) q = q (i > 1 ? "," : "") "\"" a[i] "\""
  f_cores = ("cores" in U) ? "null" : sprintf("%d", cores)
  f_load = ("load1" in U) ? "null" : sprintf("%.2f", load1)
  f_mt = ("mem_total" in U) ? "null" : sprintf("%d", mt)
  f_ma = ("mem_avail" in U) ? "null" : sprintf("%d", ma)
  f_mp = mem_ok ? sprintf("%.0f", mem_pct) : "null"
  f_disk = disk_ok ? sprintf("%d", disk) : "null"
  f_swap = ("swap" in U) ? "null" : sprintf("%.0f", swap_pct)
  printf "{\"os\":\"%s\",\"cores\":%s,\"load1\":%s,\"mem_total_mb\":%s,\"mem_avail_mb\":%s,\"mem_avail_pct\":%s,\"swap_used_pct\":%s,\"disk_free_mb\":%s,\"level\":\"%s\",\"new_local_slots\":%d,\"reason\":\"%s\",\"unreadable\":[%s]}\n",
    os, f_cores, f_load, f_mt, f_ma, f_mp, f_swap, f_disk, level, slots, why, q
}'
