#!/bin/bash

# 测试脚本 - 使用 uv 运行测试

# 检查是否安装了 uv
if ! command -v uv &> /dev/null; then
    echo "Error: uv is not installed. Please install it first:"
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# 确保虚拟环境存在
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    uv venv
fi

# 安装依赖（包括开发依赖）
echo "Installing dependencies..."
uv pip install -e ".[dev]"

# 默认测试模式
TEST_MODE=${1:-all}

case $TEST_MODE in
    unit)
        echo "Running unit tests..."
        uv run pytest tests/unit/ -v --tb=short
        ;;
    integration)
        echo "Running integration tests..."
        uv run pytest tests/integration/ -v --tb=short
        ;;
    coverage)
        echo "Running tests with coverage..."
        uv run pytest tests/ -v --cov=src/claude_code_api --cov-report=html --cov-report=term
        echo "Coverage report generated in htmlcov/index.html"
        ;;
    all)
        echo "Running all tests..."
        uv run pytest tests/ -v --tb=short
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

# 显示测试结果
if [ $? -eq 0 ]; then
    echo "✅ Tests passed successfully!"
else
    echo "❌ Tests failed!"
    exit 1
fi