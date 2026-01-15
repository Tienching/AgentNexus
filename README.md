# Virtual Human Agent

将 Claude Code CLI (`ccr` / `claude-internal`) 封装为支持流式响应的 HTTP API 服务，支持多协议适配。

## 特性

- **多协议支持**：同时支持易事厅协议和 AG-UI 协议
- **流式响应**：实时 SSE 流式输出
- **多用户隔离**：基于 agent + user + session 的目录隔离
- **协议自动识别**：根据请求格式自动选择适配器
- **会话历史查看**：内置 NexusHub 风格 Web UI，支持会话回放

## 快速开始

### 安装

```bash
# 安装 uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 克隆项目并安装依赖
git clone <repository>
cd virtual-human-sdk
uv sync

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

### 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/chat/stream/{agent_name}` | POST | 流式聊天（自动识别协议） |
| `/agui/test` | GET | AG-UI 协议测试 |
| `/nexus/` | GET | NexusHub Web UI |
| `/api/nexus/sessions` | GET | 会话列表 API |
| `/api/nexus/sessions/{id}` | GET | 会话详情 API |

### 易事厅协议（Legacy）

```bash
# 简单对话
curl --no-buffer -X POST http://localhost:8081/chat/stream/ubuntu \
  -H "Content-Type: application/json" \
  -d '{"user": "test", "content": "你好"}'
```

**请求格式：**
```json
{
  "user": "username",       // 必需：API 用户名
  "content": "你的消息",     // 必需：消息内容
  "msg_type": "text",       // 可选：消息类型
  "msg_id": "msg_001",      // 可选：消息 ID
  "session_id": "sess_001", // 可选：会话 ID
  "business_keys": []       // 可选：业务键
}
```

**响应格式 (SSE)：**
```text
event:delta
data:{"response": "你好", "finished": false, "global_output": {...}}

event:delta
data:{"response": "", "finished": true, "global_output": {"answer_success": 1}}
```

### AG-UI 协议

```bash
curl --no-buffer -X POST http://localhost:8081/chat/stream/ubuntu \
  -H "Content-Type: application/json" \
  -H "X-Protocol: agui" \
  -d '{
    "threadId": "thread-123",
    "runId": "run-456",
    "messages": [{"id": "msg-1", "role": "user", "content": "你好"}],
    "forwardedProps": {"username": "test"}
  }'
```

**请求格式：**
```json
{
  "threadId": "thread-123",           // 必需：线程 ID
  "runId": "run-456",                 // 必需：运行 ID
  "messages": [                       // 必需：消息列表
    {"id": "msg-1", "role": "user", "content": "消息内容"}
  ],
  "forwardedProps": {                 // 必需：转发属性
    "username": "api_user"            // 必需：用户名
  },
  "tools": [],                        // 可选：工具列表
  "context": [],                      // 可选：上下文
  "state": {}                         // 可选：状态
}
```

**响应格式 (SSE)：**
```text
data: {"type": "RUN_STARTED", "threadId": "...", "runId": "..."}
data: {"type": "TEXT_MESSAGE_START", "messageId": "...", "role": "assistant"}
data: {"type": "TEXT_MESSAGE_CONTENT", "messageId": "...", "delta": "你好"}
data: {"type": "TOOL_CALL_START", "toolCallId": "...", "toolCallName": "..."}
data: {"type": "TOOL_CALL_END", "toolCallId": "..."}
data: {"type": "TEXT_MESSAGE_END", "messageId": "..."}
data: {"type": "RUN_FINISHED", "threadId": "...", "runId": "..."}
```

## NexusHub Web UI

服务内置了 NexusHub 风格的 Web 界面，用于查看和管理 AGUI 会话历史。

### 访问方式

启动服务后，在浏览器中访问：
```
http://localhost:8081/nexus/
```

### 功能特性

- **会话列表**：按时间分组显示所有会话
- **搜索过滤**：支持按标题搜索、按用户筛选、按状态过滤
- **会话详情**：点击会话查看完整对话内容
- **工具调用展示**：inline 显示工具调用及其结果
- **实时更新**：运行中的会话自动刷新状态

### API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `GET /api/nexus/sessions` | GET | 获取会话列表（支持分页、搜索、状态过滤） |
| `GET /api/nexus/sessions/{id}` | GET | 获取会话详情 |
| `GET /api/nexus/sessions/{id}/messages` | GET | 获取会话消息和工具调用 |
| `DELETE /api/nexus/sessions/{id}` | DELETE | 删除会话 |
| `POST /api/nexus/sessions/{id}/cancel` | POST | 取消运行中的会话 |
| `GET /api/nexus/usernames` | GET | 获取所有用户名列表 |

### 数据存储

会话数据存储在 Redis 中，使用以下 key 模式：
- `aona:session:{sessionId}:meta` - 会话元信息
- `aona:session:{sessionId}:messages` - 消息列表
- `aona:session:{sessionId}:toolcalls` - 工具调用记录
- `aona:sessions:all` - 全局会话索引
- `aona:user:{username}:sessions` - 用户会话索引

默认 TTL 为 7 天。
```

## 配置

通过 `.env` 文件配置：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `API_HOST` | `0.0.0.0` | 监听地址 |
| `API_PORT` | `8081` | 服务端口 |
| `API_WORKERS` | `1` | 工作进程数 |
| `CCR_COMMAND` | `claude-internal` | CCR 命令 (`ccr`/`claude-internal`/`codebuddy-code`) |
| `CCR_TIMEOUT` | `120` | 命令超时（秒） |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `LOG_DIR` | `./logs` | 日志目录 |
| `USER_HOME_BASE` | `/home` | 用户目录基础路径 |
| `DEBUG` | `false` | 调试模式 |
| `REDIS_HOST` | `localhost` | Redis 服务器地址 |
| `REDIS_PORT` | `6379` | Redis 端口 |
| `REDIS_DB` | `0` | Redis 数据库 |
| `REDIS_KEY_PREFIX` | `aona:` | Redis key 前缀 |

## 项目结构

```text
virtual-human-sdk/
├── src/claude_code_api/
│   ├── app.py                 # FastAPI 应用入口
│   ├── config.py              # 配置管理
│   ├── logger.py              # 日志配置
│   ├── adapters/              # 协议适配器
│   │   ├── agui_adapter.py    # AG-UI 协议适配器
│   │   ├── legacy_adapter.py  # 易事厅协议适配器
│   │   └── protocol_router.py # 协议路由
│   ├── middleware.py          # 中间件（请求关联 ID）
│   ├── models/                # 数据模型
│   │   ├── agui_events.py     # AG-UI 事件模型
│   │   ├── claude_events.py   # Claude 事件模型
│   │   └── legacy_models.py   # 易事厅模型
│   ├── routers/               # 路由
│   │   ├── chat.py            # 聊天端点
│   │   ├── health.py          # 健康检查
│   │   └── nexus.py           # NexusHub Web API
│   ├── static/                # 静态文件
│   │   └── nexus/             # NexusHub Web UI
│   │       ├── index.html     # 主页面
│   │       ├── css/           # 样式文件
│   │       └── js/            # JavaScript 文件
│   └── services/              # 服务层
│       ├── ccr_executor.py    # CCR 命令执行器
│       ├── stream_handler.py  # 流处理器
│       ├── stream_archiver.py # 会话归档器
│       ├── session_storage.py # 会话存储服务
│       └── user_directory.py  # 用户目录管理
├── tests/                     # 测试文件
├── scripts/                   # 便捷脚本
├── prompts/                   # Prompt 模板
└── logs/                      # 日志目录
```

## 架构说明

### 协议适配

```
请求 → 协议检测 → 适配器选择
                    ├── AGUIAdapter (AG-UI 协议)
                    └── LegacyAdapter (易事厅协议)
                            ↓
                      CCRExecutor (执行 CCR 命令)
                            ↓
                      StreamHandler (流式输出)
```

### 用户目录结构

```
/home/{agent_name}/sessions/{session_id}/
```

- `agent_name`: Linux 系统用户名（用于 su 切换）
- `session_id`: 会话 ID（可选，默认 `default`）

## 测试

```bash
# 运行所有测试
./scripts/test.sh

# 单元测试
./scripts/test.sh unit

# 覆盖率报告
./scripts/test.sh coverage
```

## 生产部署

### 使用 systemd

```bash
# 复制服务文件
sudo cp virtual-human-sdk.service /etc/systemd/system/

# 启动服务
sudo systemctl daemon-reload
sudo systemctl start virtual-human-sdk
sudo systemctl enable virtual-human-sdk

# 查看状态
sudo systemctl status virtual-human-sdk

# 查看日志
sudo journalctl -fu virtual-human-sdk
```

## 调试

### 启用调试日志

```bash
# 设置环境变量
export DEBUG_STREAM=1
export DEBUG_STREAM_FILE=/tmp/debug_stream.jsonl
export ANTHROPIC_LOG=debug
```

### 常见问题

**BashTool Pre-flight check 警告**
```
⚠️ [BashTool] Pre-flight check is taking longer than expected.
```
这通常是 Anthropic API 响应延迟，不影响功能，可忽略。

**网络错误**
- 检查 API 服务是否正常运行
- 检查代理配置（如使用 agenthub）
- 查看日志确认请求是否到达后端

## License

MIT
