#!/bin/bash

# 后台运行脚本 - 在后台启动 Agent Nexus

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# 配置
HOST=${API_HOST:-0.0.0.0}
PORT=${API_PORT:-8081}
LOG_DIR=${LOG_DIR:-./logs}
PID_FILE="${LOG_DIR}/claude-api.pid"
UV_SYNC_ARGS=${UV_SYNC_ARGS:---extra dev --group dev}
PYTHON_BIN=${PYTHON_BIN:-./.venv/bin/python}
STARTUP_TIMEOUT=${STARTUP_TIMEOUT:-30}

ensure_env() {
    if ! command -v uv &> /dev/null; then
        echo "Error: uv is not installed. Please install it first:"
        echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    fi

    if [ ! -d ".venv" ]; then
        echo "Creating virtual environment..."
        uv venv
    fi

    echo "Syncing project environment with: uv sync $UV_SYNC_ARGS"
    uv sync $UV_SYNC_ARGS

    if [ ! -x "$PYTHON_BIN" ]; then
        echo "Error: expected virtual environment interpreter not found: $PYTHON_BIN"
        exit 1
    fi
}

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
echo "   日志: $LOG_DIR/api.log"

ensure_env

echo "   Python: $PYTHON_BIN"

# 直接启动虚拟环境里的 uvicorn，避免额外父进程导致 PID 文件和实际服务进程不一致
setsid "$PYTHON_BIN" -m uvicorn src.server.app:app \
    --host "$HOST" \
    --port "$PORT" \
    --log-level info \
    > "$LOG_DIR/api.log" 2>&1 < /dev/null &

# 保存实际 uvicorn 进程 PID
echo $! > "$PID_FILE"

# 等待服务启动
HEALTH_HOST="$HOST"
if [ "$HEALTH_HOST" = "0.0.0.0" ] || [ "$HEALTH_HOST" = "::" ]; then
    HEALTH_HOST="127.0.0.1"
fi

# 检查服务是否成功启动
if ps -p "$(cat "$PID_FILE")" > /dev/null 2>&1; then
    for _ in $(seq 1 "$STARTUP_TIMEOUT"); do
        if curl -fs "http://${HEALTH_HOST}:${PORT}/health" > /tmp/agent-nexus-health.json; then
            break
        fi
        sleep 1
    done

    if [ ! -s /tmp/agent-nexus-health.json ]; then
        echo "❌ Agent Nexus 健康检查超时，请检查日志: $LOG_DIR/api.log"
        tail -20 "$LOG_DIR/api.log" || true
        exit 1
    fi

    echo "✅ Agent Nexus 成功启动 (PID: $(cat "$PID_FILE"))"
    echo ""
    echo "测试健康检查："
    python3 -m json.tool < /tmp/agent-nexus-health.json
    echo ""
    echo "查看日志: tail -f $LOG_DIR/api.log"
    echo "停止服务: ./scripts/stop.sh"
else
    echo "❌ Agent Nexus 启动失败，请检查日志: $LOG_DIR/api.log"
    exit 1
fi
