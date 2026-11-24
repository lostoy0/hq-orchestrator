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
cores=1; load1=0; mem_total=0; mem_avail=0; swap_total=0; swap_used=0

if [ "$os" = "Linux" ]; then
  cores=$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1)
  if [ -r /sys/fs/cgroup/cpu.max ]; then
    read -r q p < /sys/fs/cgroup/cpu.max
    if [ "$q" != "max" ] && [ -n "${p:-}" ] && [ "$p" -gt 0 ]; then
      c=$(( (q + p - 1) / p )); [ "$c" -lt "$cores" ] && [ "$c" -gt 0 ] && cores=$c
    fi
  fi
  load1=$(cut -d' ' -f1 /proc/loadavg)
  mem_total=$(awk '/^MemTotal:/{print int($2/1024)}' /proc/meminfo)
  mem_avail=$(awk '/^MemAvailable:/{print int($2/1024)}' /proc/meminfo)
  swap_total=$(awk '/^SwapTotal:/{print int($2/1024)}' /proc/meminfo)
  swap_used=$(awk '/^SwapTotal:/{t=$2}/^SwapFree:/{f=$2}END{print int((t-f)/1024)}' /proc/meminfo)
  # cgroup v2 内存上限（容器/云端会话里比 /proc/meminfo 更真实）
  if [ -r /sys/fs/cgroup/memory.max ]; then
    lim=$(cat /sys/fs/cgroup/memory.max)
    if [ "$lim" != "max" ]; then
      lim_mb=$(( lim / 1048576 ))
      cur=$(cat /sys/fs/cgroup/memory.current 2>/dev/null || echo 0)
      inact=$(awk '/^inactive_file /{print $2}' /sys/fs/cgroup/memory.stat 2>/dev/null || echo 0)
      used_mb=$(( (cur - ${inact:-0}) / 1048576 ))
      if [ "$lim_mb" -lt "$mem_total" ]; then
        mem_total=$lim_mb
        a=$(( lim_mb - used_mb )); [ "$a" -lt "$mem_avail" ] && mem_avail=$a
      fi
    fi
  fi
elif [ "$os" = "Darwin" ]; then
  cores=$(sysctl -n hw.ncpu)
  load1=$(sysctl -n vm.loadavg | awk '{print $2}')
  mem_total=$(( $(sysctl -n hw.memsize) / 1048576 ))
  mem_avail=$(vm_stat | awk '
    /page size of/ {ps=$8}
    /Pages free/ {f=$3} /Pages inactive/ {i=$3} /Pages speculative/ {s=$3} /Pages purgeable/ {p=$3}
    END {gsub(/\./,"",f);gsub(/\./,"",i);gsub(/\./,"",s);gsub(/\./,"",p); print int((f+i+s+p)*ps/1048576)}')
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

awk -v cores="$cores" -v load1="$load1" -v mt="$mem_total" -v ma="$mem_avail" \
    -v st="${swap_total:-0}" -v su="${swap_used:-0}" -v disk="${disk_free:-0}" \
    -v pm="$PER_MEM" -v pc="$PER_CPU" -v cap="$CAP" -v os="$os" 'BEGIN {
  reserve = mt * 0.15; if (reserve < 1024) reserve = 1024          # 给系统和主会话留余量
  mem_slots = int((ma - reserve) / pm); if (mem_slots < 0) mem_slots = 0
  cpu_free = cores * 0.8 - load1
  cpu_slots = (pc > 0) ? int(cpu_free / pc) : cap; if (cpu_slots < 0) cpu_slots = 0
  slots = mem_slots; if (cpu_slots < slots) slots = cpu_slots; if (cap < slots) slots = cap
  swap_pct = (st > 0) ? su * 100 / st : 0
  mem_pct = (mt > 0) ? ma * 100 / mt : 0
  level = "GREEN"; why = ""
  if (mem_pct < 25 || load1 > cores * 0.9 || disk < 2048) { level = "YELLOW" }
  if (mem_pct < 10 || load1 > cores * 1.5 || swap_pct > 50 || disk < 512) { level = "RED"; slots = 0 }
  if (level == "YELLOW" && slots > 1) slots = 1
  if (mem_pct < 25) why = why "内存紧张;"
  if (load1 > cores * 0.9) why = why "CPU负载高;"
  if (swap_pct > 50) why = why "大量使用交换区;"
  if (disk < 2048) why = why "磁盘余量低;"
  printf "{\"os\":\"%s\",\"cores\":%d,\"load1\":%.2f,\"mem_total_mb\":%d,\"mem_avail_mb\":%d,\"mem_avail_pct\":%.0f,\"swap_used_pct\":%.0f,\"disk_free_mb\":%d,\"level\":\"%s\",\"new_local_slots\":%d,\"reason\":\"%s\"}\n",
    os, cores, load1, mt, ma, mem_pct, swap_pct, disk, level, slots, why
}'
