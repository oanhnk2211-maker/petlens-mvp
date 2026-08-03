#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=service_common.sh
source "$SCRIPT_DIR/service_common.sh"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/petlens.log"

if [[ ! -x "$PYTHON" ]]; then
    echo "错误：找不到项目虚拟环境 Python：$PYTHON" >&2
    echo "请先在项目根目录创建 .venv 并安装 requirements.txt。" >&2
    exit 1
fi

if [[ ! -f "$APP" ]]; then
    echo "错误：找不到 Streamlit 入口文件：$APP" >&2
    exit 1
fi

mkdir -p "$LOG_DIR" "$RUN_DIR"

pid="$(read_valid_pid_file 2>/dev/null || true)"
if [[ -z "$pid" ]]; then
    pid="$(find_running_petlens_pid)"
fi
if [[ -n "$pid" ]]; then
    write_pid_file "$pid"
    echo "PetLens 已在运行（PID: $pid）；PID 文件已确认。"
    echo "访问地址：$URL"
    exit 0
fi

if is_port_listening; then
    listeners="$(find_port_listener_pids | paste -sd, -)"
    echo "错误：端口 $PORT 已被非本项目进程占用（PID: ${listeners:-无法读取}），未启动 PetLens。" >&2
    exit 1
fi

cd "$PROJECT_DIR" || exit 1
# setsid --fork deliberately detaches the service from the terminal. Its $! is
# only the launcher PID, so never persist it; discover the exact Python child
# and persist that long-running PID instead.
nohup setsid --fork "$PYTHON" -m streamlit run "$APP" --server.port "$PORT" >>"$LOG_FILE" 2>&1 </dev/null &
launcher_pid=$!
pid=""

for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    pid="$(find_running_petlens_pid)"
    if is_petlens_process "$pid" && is_pid_listening "$pid" && is_web_ready; then
        write_pid_file "$pid"
        echo "PetLens 已启动（PID: $pid）"
        echo "访问地址：$URL"
        echo "日志文件：$LOG_FILE"
        exit 0
    fi
    if [[ -z "$pid" ]] && ! kill -0 "$launcher_pid" 2>/dev/null; then
        # The launcher normally exits after forking. Give the child time to
        # appear instead of treating the launcher exit as service failure.
        sleep 1
        pid="$(find_running_petlens_pid)"
    fi
    if [[ -n "$pid" ]] && ! is_petlens_process "$pid"; then
        break
    fi
    sleep 1
done

rm -f "$PID_FILE"
echo "错误：PetLens 启动失败，请查看日志：$LOG_FILE" >&2
exit 1
