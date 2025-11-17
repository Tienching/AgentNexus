#!/bin/bash
# Dify Chat Query Script
# 用于快速调用Dify API进行查询

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="$SCRIPT_DIR/dify_chat.py"

# 检查Python脚本是否存在
if [ ! -f "$PYTHON_SCRIPT" ]; then
    echo "错误: 找不到 dify_chat.py 脚本"
    exit 1
fi

# 检查是否提供了查询参数
if [ $# -eq 0 ]; then
    echo "使用方法: $0 '你的查询问题'"
    echo "示例: $0 'bgp怎么配'"
    exit 1
fi

# 将所有参数作为查询内容
QUERY="$*"

# 调用Python脚本
python3 "$PYTHON_SCRIPT" "$QUERY"