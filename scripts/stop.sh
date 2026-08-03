#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=service_common.sh
source "$SCRIPT_DIR/service_common.sh"

mapfile -t pids < <(find_petlens_pids)
if ((${#pids[@]} == 0)); then
    rm -f "$PID_FILE"
    echo "PetLens 未运行（未找到当前项目的精确匹配进程）。"
    exit 0
fi

printf '正在停止 PetLens（PID: %s）。\n' "${pids[*]}"
kill -TERM "${pids[@]}"
for _ in 1 2 3 4 5 6 7 8 9 10; do
    remaining=()
    for pid in "${pids[@]}"; do
        is_petlens_process "$pid" && remaining+=("$pid")
    done
    if ((${#remaining[@]} == 0)); then
        rm -f "$PID_FILE"
        echo "PetLens 已停止（PID: ${pids[*]}）"
        exit 0
    fi
    sleep 1
done

if ((${#remaining[@]})); then
    echo "PetLens 未在 10 秒内正常退出，正在强制停止（PID: ${remaining[*]}）。" >&2
    kill -KILL "${remaining[@]}"
fi
rm -f "$PID_FILE"
echo "PetLens 已停止（PID: ${pids[*]}）"
