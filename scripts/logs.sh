#!/usr/bin/env bash
set -u

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="$PROJECT_DIR/logs/petlens.log"

mkdir -p "$(dirname "$LOG_FILE")"
touch "$LOG_FILE"
echo "正在查看 $LOG_FILE（按 Ctrl+C 仅退出日志查看）"
exec tail -n 100 -F "$LOG_FILE"
