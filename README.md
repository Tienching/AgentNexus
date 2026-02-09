# Virtual Human Agent

将多种 CLI Provider（`claude-internal` / `gemini` / `codex`）封装为支持 **AG-UI SSE** 的 HTTP 服务，并内置 Nexus Web UI 用于会话与任务管理。

## 特性

- **AG-UI 协议优先**：统一以 AG-UI 事件流输出
- **Legacy 兼容**：支持最简 `{user, content}` 请求，后端自动转为 AG-UI
- **多 Provider**：`claude` / `gemini` / `codex` 及其 `-internal` 变体
- **多用户隔离**：按 `agent_name + session_id` 进行目录隔离
- **Nexus Web UI**：会话回放 + 任务看板 + 文件浏览
- **任务系统**：支持单任务/批量/依赖链

## 环境要求

- Python 3.10+
- Redis
- `uv`（推荐）
- 对应 Provider CLI（如 `claude-internal`、`gemini`、`codex`）

## 快速开始

### 安装

```bash
# 安装 uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 克隆项目并安装依赖
git clone <repository>
cd virtual-human-sdk-feature-aionui
uv sync

# 配置环境
cp .env.example .env
```

### 运行

```bash
# 前台启动
./scripts/run.sh

# 后台运行
./scripts/run-background.sh

# 查看状态
./scripts/status.sh

# 停止服务
./scripts/stop.sh
```

## 配置

复制 `.env.example` 为 `.env` 并根据需要修改：

```bash
cp .env.example .env
```

### 服务器配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `API_HOST` | `0.0.0.0` | 监听地址 |
| `API_PORT` | `8081` | 端口 |
| `API_WORKERS` | `1` | 进程数 |
| `ENVIRONMENT` | `development` | 运行环境 |
| `DEBUG` | `false` | 调试模式 |

### 日志配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `LOG_DIR` | `./logs` | 日志目录 |
| `LOG_MAX_BYTES` | `10485760` | 单日志文件大小 |
| `LOG_BACKUP_COUNT` | `5` | 日志备份数 |

### 用户目录配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `USER_HOME_BASE` | `/home` | 用户目录根路径 |
| `AUTO_CREATE_USER_DIR` | `true` | 自动创建用户目录 |
| `AGENT_NAME` | `ubuntu` | 默认 Agent 名称 |

### Redis 配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `REDIS_HOST` | `localhost` | Redis 地址 |
| `REDIS_PORT` | `6379` | Redis 端口 |
| `REDIS_DB` | `0` | Redis DB |
| `REDIS_PASSWORD` | | Redis 密码 |
| `REDIS_KEY_PREFIX` | `aona:` | Redis Key 前缀 |

### Provider 配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `CCR_COMMAND` | `claude` | Claude CLI 命令 |
| `CCR_TIMEOUT` | `120` | Claude 超时(秒) |
| `GEMINI_COMMAND` | `gemini` | Gemini CLI 命令 |

### Channels 配置（消息渠道）

通过配置以下环境变量启用不同的消息渠道：

**Telegram:**
| 参数 | 说明 |
|------|------|
| `TELEGRAM_BOT_TOKEN` | Bot Token（从 @BotFather 获取） |
| `TELEGRAM_ALLOWED_USERS` | 允许的用户 ID（逗号分隔，留空允许所有） |

**Slack:**
| 参数 | 说明 |
|------|------|
| `SLACK_BOT_TOKEN` | Bot OAuth Token（xoxb-开头） |
| `SLACK_APP_TOKEN` | App Token for Socket Mode（xapp-开头） |

**Discord:**
| 参数 | 说明 |
|------|------|
| `DISCORD_BOT_TOKEN` | Bot Token |

安装 Channel 依赖：
```bash
# 单独安装
pip install -e ".[telegram]"
pip install -e ".[slack]"
pip install -e ".[discord]"

# 或安装全部
pip install -e ".[all-channels]"
```

## API

### 基础端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/chat/stream` | POST | 默认 agent (`ubuntu`) 流式聊天 |
| `/chat/stream/{agent_name}` | POST | 指定 agent 流式聊天 |
| `/agui/test` | GET | AG-UI SSE 测试 |
| `/nexus/` | GET | Nexus Web UI |

### AG-UI 请求示例（推荐）

```bash
curl --no-buffer -X POST http://localhost:8081/chat/stream/ubuntu \
  -H "Content-Type: application/json" \
  -d '{
    "threadId": "thread-123",
    "runId": "run-456",
    "messages": [{"id": "msg-1", "role": "user", "content": "你好"}],
    "forwardedProps": {"username": "test"},
    "provider": "gemini-internal"
  }'
```

### Legacy 最简请求（自动转 AG-UI）

```bash
curl --no-buffer -X POST http://localhost:8081/chat/stream/ubuntu \
  -H "Content-Type: application/json" \
  -d '{"user": "test", "content": "你好", "provider": "claude-internal"}'
```

> Provider 也可通过 `X-Provider` 头或 `provider` 字段指定；若缺省，则默认 `claude`。

## Nexus Web UI

访问：
```
http://localhost:8081/nexus/
```

### 会话 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/nexus/sessions` | GET | 会话列表（分页/搜索/状态） |
| `/api/nexus/sessions/{id}` | GET | 会话详情 |
| `/api/nexus/sessions/{id}/messages` | GET | 会话消息+工具调用 |
| `/api/nexus/sessions/{id}/cancel` | POST | 取消会话 |
| `/api/nexus/sessions/{id}` | DELETE | 删除会话 |
| `/api/nexus/sessions/bulk_delete` | POST | 批量删除会话 |
| `/api/nexus/usernames` | GET | 用户名列表 |
| `/api/nexus/agents` | GET | 可用 Agent 列表 |

### 任务 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/nexus/tasks` | GET | 任务列表 |
| `/api/nexus/tasks` | POST | 创建任务 |
| `/api/nexus/tasks/bulk` | POST | 批量创建任务 |
| `/api/nexus/tasks/{id}` | GET | 任务详情 |
| `/api/nexus/tasks/{id}` | DELETE | 删除任务 |
| `/api/nexus/tasks/{id}/status` | PATCH | 更新任务状态 |
| `/api/nexus/tasks/bulk_archive` | POST | 批量归档 |
| `/api/nexus/tasks/bulk_unarchive` | POST | 批量反归档 |
| `/api/nexus/tasks/bulk_clear` | POST | 清理归档任务 |
| `/api/nexus/tasks/bulk_delete` | POST | 强制批量删除 |
| `/api/nexus/tasks/{id}/agui/messages` | GET | 任务对话快照 |
| `/api/nexus/tasks/{id}/agui/stream` | GET | 任务对话 SSE 回放 |

### Task 创建模式

- **Single Task**：创建 1 条任务
- **Bulk Create**：一行一个任务，互不依赖
- **Task Chain**：一行一个任务，后一个依赖前一个

## 项目结构（核心）

```
virtual-human-sdk-feature-aionui/
├── .env.example                # 配置模板
├── src/server/                 # FastAPI 服务（路由/服务/适配器/模型）
├── src/runtime/                # 运行时核心（事件/适配器/存储/执行流）
├── src/providers/              # Provider 实现（claude/gemini/codex）
├── src/providers/runtime/      # Provider 运行时抽象
├── src/channels/               # 消息渠道（Telegram/Slack/Discord 等）
├── src/server/static/nexus/    # Nexus Web UI
├── scripts/                    # 启停脚本
└── tests/                      # 测试
```

## 测试

```bash
./scripts/test.sh
./scripts/test.sh unit
./scripts/test.sh coverage
```

## License

MIT
