#!/bin/bash

# 查看 Virtual Human Agent 的运行状态

LOG_DIR=${LOG_DIR:-./logs}
PID_FILE="${LOG_DIR}/claude-api.pid"
HOST=${API_HOST:-0.0.0.0}
PORT=${API_PORT:-8081}

echo "======================================"
echo "    Virtual Human Agent 状态检查"
echo "======================================"
echo ""

# 检查 PID 文件
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "✅ Virtual Human Agent 正在运行"
        echo "   PID: $PID"
        echo "   内存使用:"
        ps -p "$PID" -o pid,vsz,rss,comm | tail -1
    else
        echo "⚠️  PID 文件存在但进程未运行"
        rm -f "$PID_FILE"
    fi
else
    echo "ℹ️  PID 文件不存在"
fi

# 查找所有相关进程
echo ""
echo "📊 所有 API 进程:"
ps aux | grep -v grep | grep "uvicorn src.server.app:app" || echo "   没有找到运行中的进程"

# 测试健康检查
echo ""
echo "🏥 健康检查 (http://${HOST}:${PORT}/health):"
if curl -s -o /dev/null -w "%{http_code}" "http://${HOST}:${PORT}/health" | grep -q "200"; then
    curl -s "http://${HOST}:${PORT}/health" | python3 -m json.tool
else
    echo "   ❌ Virtual Human Agent 服务不可用"
fi

# 显示最新日志
if [ -f "$LOG_DIR/api.log" ]; then
    echo ""
    echo "📝 最新日志 (最后 5 行):"
    tail -5 "$LOG_DIR/api.log"
fi

echo ""
echo "======================================"