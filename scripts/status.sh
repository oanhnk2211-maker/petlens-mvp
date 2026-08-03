#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=service_common.sh
source "$SCRIPT_DIR/service_common.sh"

echo "访问地址：$URL"

pid="$(read_valid_pid_file 2>/dev/null || true)"
repaired=0
if [[ -z "$pid" ]]; then
    pid="$(find_running_petlens_pid)"
    if [[ -n "$pid" ]] && is_pid_listening "$pid"; then
        write_pid_file "$pid"
        repaired=1
    else
        echo "服务状态：未运行"
        echo "PID：无"
        if is_port_listening; then
            echo "端口检查：$PORT 正在监听，但不是本项目的精确匹配进程"
        else
            echo "端口检查：$PORT 未监听"
        fi
        echo "网页检查：未检查（服务未运行）"
        exit 1
    fi
fi

echo "服务状态：运行中"
echo "PID：$pid"
if ((repaired)); then
    echo "PID 文件：已自动修复"
else
    echo "PID 文件：有效"
fi
if is_pid_listening "$pid"; then
    echo "端口检查：$PORT 由 PID $pid 监听"
else
    echo "端口检查：$PORT 未由 PID $pid 监听"
    exit 1
fi

if is_web_ready; then
    echo "网页检查：响应正常"
else
    echo "网页检查：暂时无法响应"
    exit 1
fi
