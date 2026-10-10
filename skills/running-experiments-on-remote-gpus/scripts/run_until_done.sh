#!/bin/bash
# 在一张 GPU 上反复运行一条命令,直到完成检查通过或用完尝试次数。在远端用 screen 脱离启动。
#   run_until_done.sh <gpu> <max_attempts> <done_check> -- <command> [args...]
# <gpu>          传给 CUDA_VISIBLE_DEVICES 的值,如 0 或 0,1。
# <max_attempts> 正整数。只限制尝试次数,不限制单次运行时长。
# <done_check>   一条非空 shell 命令,退出码 0 表示全部任务项已完成。
# <command>      必须自己跳过已完成的任务项。
# 退出码: 0 完成检查通过; 1 用完尝试次数仍未通过; 2 参数错误。<command> 的退出码只写入输出,不作为本脚本的退出码。
usage() { echo "usage: $0 <gpu> <max_attempts> <done_check> -- <command> [args...]" >&2; exit 2; }
[ $# -ge 5 ] && [ "$4" = "--" ] || usage
[[ $1 =~ ^[0-9]+(,[0-9]+)*$ ]] || usage
[[ $2 =~ ^[1-9][0-9]*$ ]] || usage
[ -n "$3" ] || usage
export CUDA_VISIBLE_DEVICES=$1
max=$2 check=$3
shift 4
attempt=1
while [ "$attempt" -le "$max" ]; do
  if bash -c "$check"; then
    echo "=== DONE before attempt $attempt $(date -Is) ==="
    exit 0
  fi
  echo "=== RUN attempt $attempt/$max on GPU $CUDA_VISIBLE_DEVICES $(date -Is) ==="
  "$@"
  echo "=== RUN attempt $attempt exit=$? $(date -Is) ==="
  attempt=$((attempt + 1))
done
if bash -c "$check"; then
  echo "=== DONE $(date -Is) ==="
  exit 0
fi
echo "=== NOT DONE after $max attempts $(date -Is) ==="
exit 1
