#!/bin/bash

# 启动脚本 - 使用统一的 uv bootstrap 路径运行 FastAPI 应用

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# 设置默认值
HOST=${API_HOST:-0.0.0.0}
PORT=${API_PORT:-8081}
RELOAD=${RELOAD:-true}
UV_SYNC_ARGS=${UV_SYNC_ARGS:---extra dev --group dev}
PYTHON_BIN="./.venv/bin/python"

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

echo "Starting Agent Nexus..."
echo "Host: $HOST"
echo "Port: $PORT"
echo "Reload: $RELOAD"

ensure_env

# 启动应用
if [ "$RELOAD" = "true" ]; then
    echo "Starting in development mode (with auto-reload)..."
    exec "$PYTHON_BIN" -m uvicorn src.server.app:app \
        --host "$HOST" \
        --port "$PORT" \
        --reload \
        --log-level info
else
    echo "Starting in production mode..."
    exec "$PYTHON_BIN" -m uvicorn src.server.app:app \
        --host "$HOST" \
        --port "$PORT" \
        --workers "${API_WORKERS:-4}" \
        --log-level info
fi
