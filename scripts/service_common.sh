#!/usr/bin/env bash

# Shared, project-specific process discovery for the PetLens Streamlit service.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"
APP="$PROJECT_DIR/streamlit_app.py"
RUN_DIR="$PROJECT_DIR/run"
PID_FILE="$RUN_DIR/petlens.pid"
PORT=8501
URL="http://localhost:$PORT"

is_petlens_process() {
    local pid="$1"
    local -a argv=()
    local i

    [[ "$pid" =~ ^[0-9]+$ ]] || return 1
    [[ -r "/proc/$pid/cmdline" ]] || return 1
    mapfile -d '' -t argv < "/proc/$pid/cmdline"
    ((${#argv[@]} >= 5)) || return 1
    [[ "${argv[0]}" == "$PYTHON" ]] || return 1

    for ((i = 1; i + 3 < ${#argv[@]}; i++)); do
        if [[ "${argv[i]}" == "-m" &&
              "${argv[i + 1]}" == "streamlit" &&
              "${argv[i + 2]}" == "run" &&
              "${argv[i + 3]}" == "$APP" ]]; then
            return 0
        fi
    done
    return 1
}

find_petlens_pids() {
    local proc pid
    for proc in /proc/[0-9]*; do
        pid="${proc##*/}"
        if is_petlens_process "$pid"; then
            printf '%s\n' "$pid"
        fi
    done
}

# Linux exposes listening socket inodes in /proc/net/tcp{,6}. Map those
# inodes back to process file descriptors without matching unrelated commands.
find_port_listener_pids() {
    local port_hex inode proc fd target pid
    local -a inodes=()
    port_hex="$(printf '%04X' "$PORT")"

    mapfile -t inodes < <(
        awk -v port=":$port_hex" \
            '$2 ~ (port "$") && $4 == "0A" { print $10 }' \
            /proc/net/tcp /proc/net/tcp6 2>/dev/null
    )
    ((${#inodes[@]})) || return 0

    for proc in /proc/[0-9]*; do
        pid="${proc##*/}"
        for fd in "$proc"/fd/*; do
            [[ -L "$fd" ]] || continue
            target="$(readlink "$fd" 2>/dev/null)" || continue
            for inode in "${inodes[@]}"; do
                if [[ "$target" == "socket:[$inode]" ]]; then
                    printf '%s\n' "$pid"
                    break 2
                fi
            done
        done
    done
}

is_port_listening() {
    local port_hex
    port_hex="$(printf '%04X' "$PORT")"
    awk -v port=":$port_hex" \
        '$2 ~ (port "$") && $4 == "0A" { found=1; exit }
         END { exit !found }' \
        /proc/net/tcp /proc/net/tcp6 2>/dev/null
}

is_pid_listening() {
    local wanted="$1" pid
    while IFS= read -r pid; do
        [[ "$pid" == "$wanted" ]] && return 0
    done < <(find_port_listener_pids)
    return 1
}

find_running_petlens_pid() {
    local pid first=""
    while IFS= read -r pid; do
        [[ -n "$first" ]] || first="$pid"
        if is_pid_listening "$pid"; then
            printf '%s\n' "$pid"
            return 0
        fi
    done < <(find_petlens_pids)

    # During startup the exact process can exist briefly before it listens.
    [[ -n "$first" ]] && printf '%s\n' "$first"
}

write_pid_file() {
    local pid="$1" tmp
    mkdir -p "$RUN_DIR"
    tmp="$PID_FILE.$$"
    printf '%s\n' "$pid" > "$tmp"
    mv -f "$tmp" "$PID_FILE"
}

read_valid_pid_file() {
    local pid
    [[ -f "$PID_FILE" ]] || return 1
    pid="$(tr -d '[:space:]' < "$PID_FILE")"
    is_petlens_process "$pid" || return 1
    printf '%s\n' "$pid"
}

is_web_ready() {
    "$PYTHON" - "$URL" <<'PY' 2>/dev/null
import sys
import urllib.request

try:
    with urllib.request.urlopen(sys.argv[1], timeout=3) as response:
        raise SystemExit(0 if response.status < 400 else 1)
except Exception:
    raise SystemExit(1)
PY
}
