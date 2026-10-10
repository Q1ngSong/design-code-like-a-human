#!/bin/bash
# 周期调用 sync_remote_outputs.py,直到停止文件出现。主工作站是 Linux 时使用,放在 screen 会话里运行。
#   sync_loop.sh <python> <config.json> <stop_file> [interval_seconds]
# 停止:创建停止文件;当前一轮结束后 10 秒内退出,并输出 LOOP STOPPED。退出码: 0 正常停止; 2 参数错误。
[ $# -ge 3 ] && [[ ${4:-1200} =~ ^[1-9][0-9]*$ ]] || { echo "usage: $0 <python> <config.json> <stop_file> [interval_seconds]" >&2; exit 2; }
python=$1 config=$2 stop=$3 interval=${4:-1200}
here=$(cd "$(dirname "$0")" && pwd)
while [ ! -e "$stop" ]; do
  echo "=== PASS $(date -Is) ==="
  "$python" "$here/sync_remote_outputs.py" "$config"
  echo "=== PASS exit=$? $(date -Is) ==="
  waited=0
  while [ "$waited" -lt "$interval" ] && [ ! -e "$stop" ]; do sleep 10; waited=$((waited + 10)); done
done
echo "=== LOOP STOPPED $(date -Is) ==="
