#!/bin/bash

# 启动脚本 - 使用 uv 运行 FastAPI 应用

# 设置默认值
HOST=${API_HOST:-0.0.0.0}
PORT=${API_PORT:-8081}
RELOAD=${RELOAD:-true}

echo "Starting Claude Code API..."
echo "Host: $HOST"
echo "Port: $PORT"
echo "Reload: $RELOAD"

# 检查是否安装了 uv
if ! command -v uv &> /dev/null; then
    echo "Error: uv is not installed. Please install it first:"
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# 确保虚拟环境存在并安装依赖
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    uv venv
fi

echo "Installing dependencies..."
uv sync

# 启动应用
if [ "$RELOAD" = "true" ]; then
    echo "Starting in development mode (with auto-reload)..."
    uv run uvicorn src.claude_code_api.api:app \
        --host $HOST \
        --port $PORT \
        --reload \
        --log-level info
else
    echo "Starting in production mode..."
    uv run uvicorn src.claude_code_api.api:app \
        --host $HOST \
        --port $PORT \
        --workers ${API_WORKERS:-4} \
        --log-level info
fi
