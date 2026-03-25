#!/bin/bash

# 停止后台运行的 Agent Nexus

set -euo pipefail

LOG_DIR=${LOG_DIR:-./logs}
PID_FILE="${LOG_DIR}/claude-api.pid"
PATTERN="uvicorn src.server.app:app"

collect_pids() {
    {
        if [ -f "$PID_FILE" ]; then
            cat "$PID_FILE"
        fi
        pgrep -f "$PATTERN" || true
    } | awk 'NF' | sort -u
}

PIDS=$(collect_pids)
if [ -z "$PIDS" ]; then
    echo "❌ 没有找到运行中的 Agent Nexus 进程"
    rm -f "$PID_FILE"
    exit 1
fi

echo "🛑 正在停止 Agent Nexus 进程: $PIDS"
kill $PIDS || true

# 等待所有相关进程退出
for i in {1..8}; do
    STILL_RUNNING=""
    for PID in $PIDS; do
        if ps -p "$PID" > /dev/null 2>&1; then
            STILL_RUNNING="$STILL_RUNNING $PID"
        fi
    done
    if [ -z "$STILL_RUNNING" ]; then
        break
    fi
    sleep 1
done

# 如果仍然有进程存活，强制终止
FORCE_PIDS=""
for PID in $PIDS; do
    if ps -p "$PID" > /dev/null 2>&1; then
        FORCE_PIDS="$FORCE_PIDS $PID"
    fi
done
if [ -n "$FORCE_PIDS" ]; then
    echo "⚠️  进程未完全退出，强制终止:$FORCE_PIDS"
    kill -9 $FORCE_PIDS || true
fi

rm -f "$PID_FILE"
echo "✅ Agent Nexus 已停止"
