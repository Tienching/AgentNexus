#!/bin/bash
#
# deploy.sh - 部署 prompts 配置到指定用户的 .claude-internal 目录
#
# 用法:
#   ./deploy.sh <username>
#   ./deploy.sh ubuntu        # 部署到 /home/ubuntu/.claude-internal
#   ./deploy.sh tencent       # 部署到 /home/tencent/.claude-internal
#   ./deploy.sh root          # 部署到 /root/.claude-internal
#

set -e

# 脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PROMPTS_DIR="$PROJECT_ROOT/prompts"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

usage() {
    echo "用法: $0 <username>"
    echo ""
    echo "将 prompts 目录下的配置部署到指定用户的 .claude-internal 目录"
    echo ""
    echo "参数:"
    echo "  username    目标用户名 (例如: ubuntu, tencent, root)"
    echo ""
    echo "示例:"
    echo "  $0 ubuntu       # 部署到 /home/ubuntu/.claude-internal"
    echo "  $0 root         # 部署到 /root/.claude-internal"
    exit 1
}

# 检查参数
if [ $# -ne 1 ]; then
    log_error "缺少用户名参数"
    usage
fi

USERNAME="$1"

# 确定目标目录
if [ "$USERNAME" = "root" ]; then
    TARGET_DIR="/root/.claude-internal"
else
    TARGET_DIR="/home/$USERNAME/.claude-internal"
fi

# 检查 prompts 目录是否存在
if [ ! -d "$PROMPTS_DIR" ]; then
    log_error "Prompts 目录不存在: $PROMPTS_DIR"
    exit 1
fi

# 检查用户主目录是否存在
if [ "$USERNAME" = "root" ]; then
    USER_HOME="/root"
else
    USER_HOME="/home/$USERNAME"
fi

if [ ! -d "$USER_HOME" ]; then
    log_error "用户主目录不存在: $USER_HOME"
    exit 1
fi

log_info "开始部署配置..."
log_info "  源目录: $PROMPTS_DIR"
log_info "  目标目录: $TARGET_DIR"

# 创建目标目录（如果不存在）
if [ ! -d "$TARGET_DIR" ]; then
    log_info "创建目标目录: $TARGET_DIR"
    mkdir -p "$TARGET_DIR"
fi

# 备份现有配置
BACKUP_DIR="$TARGET_DIR.backup.$(date +%Y%m%d_%H%M%S)"
log_info "备份现有配置到: $BACKUP_DIR"
cp -r "$TARGET_DIR" "$BACKUP_DIR"

# 同步 prompts 目录下的所有内容到目标目录（先删后复制，确保完全同步）
log_info "同步配置文件..."
for item in "$PROMPTS_DIR"/* "$PROMPTS_DIR"/.*; do
    base_name=$(basename "$item")
    [ "$base_name" = "." ] || [ "$base_name" = ".." ] && continue
    [ ! -e "$item" ] && continue
    rm -rf "$TARGET_DIR/$base_name"
    cp -r "$item" "$TARGET_DIR/$base_name"
done

# 设置正确的权限
log_info "设置目录权限..."
if [ "$USERNAME" != "root" ]; then
    if id "$USERNAME" &>/dev/null; then
        chown -R "$USERNAME:$USERNAME" "$TARGET_DIR"
        log_info "已将 $TARGET_DIR 的所有者设置为 $USERNAME"
    else
        log_warn "用户 $USERNAME 不存在，无法设置权限"
    fi
fi

chmod -R 755 "$TARGET_DIR"

# 显示部署结果
log_info "部署完成！目标目录: $TARGET_DIR"
