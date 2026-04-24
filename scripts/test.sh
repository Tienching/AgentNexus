#!/bin/bash

# 测试脚本 - 使用统一的 uv bootstrap 路径运行测试

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

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

ensure_env

# 默认测试模式
TEST_MODE=${1:-all}
PYTEST_EXPR=${PYTEST_EXPR:-not optional_backend}

case $TEST_MODE in
    unit)
        echo "Running unit tests..."
        "$PYTHON_BIN" -m pytest tests/ -v --tb=short -m "($PYTEST_EXPR) and unit"
        ;;
    integration)
        echo "Running integration tests..."
        "$PYTHON_BIN" -m pytest tests/ -v --tb=short -m "($PYTEST_EXPR) and integration"
        ;;
    coverage)
        echo "Running tests with coverage..."
        "$PYTHON_BIN" -m pytest tests/ -v -m "$PYTEST_EXPR" --cov=src --cov-report=html --cov-report=term
        echo "Coverage report generated in htmlcov/index.html"
        ;;
    all)
        echo "Running all tests..."
        "$PYTHON_BIN" -m pytest tests/ -v --tb=short -m "$PYTEST_EXPR"
        ;;
    *)
        echo "Usage: $0 [unit|integration|coverage|all]"
        echo "  unit        - Run unit tests only"
        echo "  integration - Run integration tests only"
        echo "  coverage    - Run all tests with coverage report"
        echo "  all         - Run all tests (default)"
        exit 1
        ;;
esac

echo "✅ Tests passed successfully!"
