#!/bin/bash

# 后台运行脚本 - 在后台启动 Agent Nexus

set -euo pipefail

# 配置
HOST=${API_HOST:-0.0.0.0}
PORT=${API_PORT:-8081}
LOG_DIR=${LOG_DIR:-./logs}
PID_FILE="${LOG_DIR}/claude-api.pid"
PYTHON_BIN=${PYTHON_BIN:-./.venv/bin/python3}

if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN=$(command -v python3)
fi

# 创建日志目录
mkdir -p "$LOG_DIR"

# 检查是否已经在运行
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo "⚠️  Agent Nexus 已经在运行中 (PID: $OLD_PID)"
        echo "使用 './scripts/stop.sh' 停止服务"
        exit 1
    fi
    rm -f "$PID_FILE"
fi

echo "🚀 在后台启动 Agent Nexus..."
echo "   Host: $HOST"
echo "   Port: $PORT"
echo "   Python: $PYTHON_BIN"
echo "   日志: $LOG_DIR/api.log"

# 直接启动 uvicorn，避免 'uv run' 额外父进程导致 PID 文件和实际服务进程不一致
nohup "$PYTHON_BIN" -m uvicorn src.server.app:app \
    --host "$HOST" \
    --port "$PORT" \
    --log-level info \
    > "$LOG_DIR/api.log" 2>&1 &

# 保存实际 uvicorn 进程 PID
echo $! > "$PID_FILE"

# 等待服务启动
sleep 2

# 检查服务是否成功启动
if ps -p "$(cat "$PID_FILE")" > /dev/null 2>&1; then
    echo "✅ Agent Nexus 成功启动 (PID: $(cat "$PID_FILE"))"
    echo ""
    echo "测试健康检查："
    curl -s "http://${HOST}:${PORT}/health" | python3 -m json.tool
    echo ""
    echo "查看日志: tail -f $LOG_DIR/api.log"
    echo "停止服务: ./scripts/stop.sh"
else
    echo "❌ Agent Nexus 启动失败，请检查日志: $LOG_DIR/api.log"
    exit 1
fi
