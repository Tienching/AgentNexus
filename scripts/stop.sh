#!/bin/bash

# 停止后台运行的 Claude Code API

LOG_DIR=${LOG_DIR:-./logs}
PID_FILE="${LOG_DIR}/claude-api.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "⚠️  PID 文件不存在"
    echo "尝试通过进程名查找..."

    # 尝试通过进程名停止
    PIDS=$(pgrep -f "uvicorn src.claude_code_api.app:app")
    if [ -z "$PIDS" ]; then
        echo "❌ 没有找到运行中的 API 进程"
        exit 1
    else
        echo "找到进程: $PIDS"
        kill $PIDS
        echo "✅ 已停止所有 API 进程"
        exit 0
    fi
fi

PID=$(cat "$PID_FILE")

if ps -p "$PID" > /dev/null 2>&1; then
    echo "🛑 正在停止 Claude Code API (PID: $PID)..."
    kill "$PID"

    # 等待进程结束
    for i in {1..5}; do
        if ! ps -p "$PID" > /dev/null 2>&1; then
            break
        fi
        sleep 1
    done

    # 如果进程仍在运行，强制终止
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "⚠️  进程未响应，强制终止..."
        kill -9 "$PID"
    fi

    rm -f "$PID_FILE"
    echo "✅ API 已停止"
else
    echo "⚠️  进程不存在 (PID: $PID)"
    rm -f "$PID_FILE"

    # 尝试通过进程名停止
    PIDS=$(pgrep -f "uvicorn src.claude_code_api.app:app")
    if [ ! -z "$PIDS" ]; then
        echo "找到其他 API 进程: $PIDS"
        kill $PIDS
        echo "✅ 已停止所有 API 进程"
    fi
fi