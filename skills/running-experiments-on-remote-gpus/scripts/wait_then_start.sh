#!/bin/bash
# 等指定的 screen 会话全部结束、指定 GPU 上没有计算进程后,在该 GPU 上启动一条命令。在远端用 screen 脱离启动。
#   wait_then_start.sh <gpu> <timeout_seconds> <session[,session...]> -- <command> [args...]
# <gpu>             单个 GPU 编号;命令启动时 CUDA_VISIBLE_DEVICES 被设为它。
# <timeout_seconds> 正整数,只限制等待阶段;命令启动后不受它限制。
# <session>         screen 会话名,按字面全名比较。
# 会话结束不代表其任务成功;<command> 依赖前序结果时,由 <command> 自己检查前序的完成条件。
# 退出码: 3 等待超时; 4 nvidia-smi 查询失败或 30 秒无响应; 2 参数错误; 其余为 <command> 的退出码。
# 输出的最后一个 "=== ... ===" 行说明停在哪个阶段(TIMEOUT / QUERY FAILED / START)。
usage() { echo "usage: $0 <gpu> <timeout_seconds> <session[,session...]> -- <command> [args...]" >&2; exit 2; }
[ $# -ge 5 ] && [ "$4" = "--" ] || usage
[[ $1 =~ ^[0-9]+$ ]] || usage
[[ $2 =~ ^[1-9][0-9]*$ ]] || usage
[ -n "$3" ] || usage
gpu=$1 deadline=$((SECONDS + $2))
IFS=, read -r -a sessions <<< "$3"
shift 4
alive() {  # 是否还有列出的会话存在;screen -ls 的每行第一列形如 <pid>.<name>
  local name
  for name in "${sessions[@]}"; do
    screen -ls | awk '{print $1}' | sed 's/^[0-9]*\.//' | grep -Fxq -- "$name" && return 0
  done
  return 1
}
busy() {  # 0 = GPU 上还有计算进程; 1 = 没有; 查询失败则退出 4
  local apps
  apps=$(timeout 30 nvidia-smi --query-compute-apps=pid --format=csv,noheader -i "$gpu") \
    || { echo "=== QUERY FAILED nvidia-smi $(date -Is) ==="; exit 4; }
  [ -n "$apps" ]
}
while alive || busy; do
  [ $SECONDS -ge $deadline ] && { echo "=== TIMEOUT $(date -Is) ==="; exit 3; }
  sleep 30
done
[ $SECONDS -ge $deadline ] && { echo "=== TIMEOUT $(date -Is) ==="; exit 3; }
echo "=== START on GPU $gpu $(date -Is) ==="
CUDA_VISIBLE_DEVICES=$gpu "$@"
