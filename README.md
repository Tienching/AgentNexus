# Claude Code API

将 `ccr code` CLI 封装为支持流式响应的 HTTP API 服务。

## 快速开始

### 安装

```bash
# 安装 uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 克隆项目并安装依赖
git clone <repository>
cd claude_code_api
uv venv
uv pip sync

# 配置环境
cp .env.example .env
```

### 运行

```bash
# 快速启动（开发模式）
./scripts/run.sh

# 后台运行
./scripts/run-background.sh

# 查看状态
./scripts/status.sh

# 停止服务
./scripts/stop.sh
```

## API 使用

### 基础示例

```bash
# 健康检查
curl http://localhost:8081/health

# 简单对话
curl -X POST http://localhost:8081/chat/stream/test \
  -H "Content-Type: application/json" \
  -d '{"user": "test", "content": "你好"}'

# 实时显示流式响应
curl --no-buffer -X POST http://localhost:8081/chat/stream/test \
  -H "Content-Type: application/json" \
  -d '{"user": "test", "content": "介绍一下Python"}'
```

### 请求格式

```json
{
  "user": "username",       # 必需
  "content": "你的消息",     # 必需
  "msg_type": "text",       # 可选，默认 "text"
  "msg_id": "msg_001",      # 可选
  "session_id": "sess_001", # 可选
  "business_keys": []       # 可选
}
```

### 响应格式 (SSE)

```text
event:delta
data:{"response": "你", "finished": false, "global_output": {...}}

event:delta
data:{"response": "好", "finished": false, "global_output": {...}}

event:delta
data:{"response": "", "finished": true, "global_output": {"answer_success": 1, ...}}
```

## 配置

通过 `.env` 文件配置，主要参数：

- `API_PORT=8081` - 服务端口
- `CCR_TIMEOUT=120` - CCR 命令超时（秒）
- `LOG_LEVEL=INFO` - 日志级别

## 测试

```bash
# 运行所有测试
./scripts/test.sh

# 单元测试
./scripts/test.sh unit

# 覆盖率报告
./scripts/test.sh coverage
```

## 项目结构

```text
claude_code_api/
├── src/claude_code_api/    # 源代码
│   ├── api.py              # FastAPI 应用
│   ├── ccr_service.py      # 核心服务逻辑
│   └── models.py           # 数据模型
├── tests/                  # 测试文件
├── scripts/                # 便捷脚本
└── logs/                   # 日志目录
```

## 生产部署

### 使用 systemd（推荐）

```bash
# 复制并编辑服务文件
sudo cp claude-api.service.example /etc/systemd/system/claude-api.service
sudo nano /etc/systemd/system/claude-api.service

# 启动服务
sudo systemctl start claude-api
sudo systemctl enable claude-api

# 查看服务状态
sudo systemctl status claude-api

# 查看服务日志
sudo journalctl -fu claude-api.service          # 实时查看日志
sudo journalctl -xeu claude-api.service -f      # 详细日志并实时跟踪
sudo journalctl -u claude-api.service -n 100    # 查看最近100行日志
sudo journalctl -u claude-api.service --since today  # 查看今天的日志

# 重启服务
sudo systemctl restart claude-api

# 停止服务
sudo systemctl stop claude-api
```

## License

MIT
