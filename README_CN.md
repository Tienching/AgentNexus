# Agent Runtime SDK

[English Documentation](./README.md)

将多种 CLI Provider（Claude / Gemini / Codex 等）封装为支持 **AG-UI SSE** 流式输出的 HTTP 服务，内置会话/任务管理系统和多渠道消息集成。

## 特性

- **AG-UI 协议优先** — 统一以 AG-UI 事件流输出
- **Legacy 兼容** — 支持最简 `{user, content}` 请求，后端自动转为 AG-UI
- **多 Provider** — Claude / Gemini / Codex / CodeBuddy 及其 `-internal` 变体
- **多用户隔离** — 按 `exec_user + session_id` 进行目录隔离
- **Nexus Web UI** — 会话回放 + 任务看板 + 文件浏览
- **任务系统** — 支持单任务/批量/依赖链，带并发控制
- **多渠道集成** — Telegram、Slack、Discord、飞书 (Feishu/Lark)、WhatsApp、Signal
- **CLI 工具 (`anexus`)** — 支持 onboard/init/install/start/stop/status/config/list 子命令
- **Systemd 就绪** — 自带 `.service` 文件，可直接用于生产部署

## 环境要求

- Python 3.11+
- Redis
- [`uv`](https://github.com/astral-sh/uv)（推荐）
- 对应 Provider CLI（如 `claude`、`gemini`、`codex`）

## 快速开始

### 安装

```bash
# 安装 uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 克隆项目并安装依赖
git clone <仓库地址>
cd <项目目录>
uv sync
```

### 一站式配置向导（推荐首次使用）

```bash
anexus onboard
```

交互式向导将引导你完成 **6 个步骤**：

1. **环境检查** — 创建目录和 `.env` 文件
2. **核心配置** — API 地址、端口、执行用户
3. **Provider 选择** — 选择默认 Provider（CodeBuddy / Claude / Gemini / Codex）
4. **Channel 选择** — 多选消息渠道（Telegram、Slack、Discord、飞书、WhatsApp、Signal），逐个引导配置 Token
5. **依赖安装** — 自动安装已选渠道的依赖
6. **启动服务** — 前台或守护进程模式启动

可选参数：`--reset`（重置 .env）、`--skip-install`、`--skip-start`

### 手动配置

```bash
# 手动配置环境变量
cp .env.example .env
# 编辑 .env 填入你的配置
```

### 通过 `anexus` CLI 运行

```bash
# 初始化项目（创建 .env、目录等）
anexus init

# 安装渠道依赖
anexus install channel telegram
anexus install channel discord
anexus install channel feishu
anexus install channel all        # 安装所有渠道

# 前台启动服务
anexus start

# 后台启动服务（守护进程模式）
anexus start --daemon

# 查看服务状态
anexus status

# 停止服务
anexus stop

# 交互式配置向导
anexus config wizard

# 列出已安装的插件
anexus list
```

### 通过脚本运行（备选方式）

```bash
./scripts/run.sh                  # 前台启动（开发模式，带热重载）
./scripts/run-background.sh       # 后台运行（守护进程模式）
./scripts/status.sh               # 查看状态
./scripts/stop.sh                 # 停止服务
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
| `EXEC_USER` | `ubuntu` | 默认执行用户（Linux 用户名） |

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
| `CLI_COMMAND` | `claude` | CLI 执行器默认命令 |
| `CLI_TIMEOUT` | `120` | CLI 执行器超时（秒） |
| `GEMINI_COMMAND` | `gemini` | Gemini CLI 命令 |
| `DEFAULT_PROVIDER` | `codebuddy` | 默认 Provider |
| `DEFAULT_ALIAS` | | 默认 Provider 别名 |

### 流式输出配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `STREAM_CHUNK_SIZE` | `100` | 每块字符数 |
| `STREAM_DELAY_MS` | `50` | 块间延迟（毫秒） |
| `STREAM_BUFFER_SIZE` | `1000` | 流缓冲区大小 |

### 任务执行器配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `EXECUTOR_ENABLED` | `true` | 启用任务执行器 |
| `EXECUTOR_DEFAULT_MAX_CONCURRENCY` | `3` | 最大并发任务数 |

### Nexus Web UI 配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `NEXUS_PASSWORD` | | UI 密码（空则免认证） |
| `NEXUS_SESSION_TTL` | `86400` | 会话 TTL（秒） |

### 消息渠道配置

通过配置以下环境变量启用不同的消息渠道：

**Telegram:**

| 参数 | 说明 |
|------|------|
| `TELEGRAM_BOT_TOKEN` | Bot Token（从 @BotFather 获取） |
| `TELEGRAM_ALLOWED_USERS` | 允许的用户 ID（逗号分隔，留空允许所有） |

**Slack:**

| 参数 | 说明 |
|------|------|
| `SLACK_BOT_TOKEN` | Bot OAuth Token（xoxb- 开头） |
| `SLACK_APP_TOKEN` | App Token for Socket Mode（xapp- 开头） |

**Discord:**

| 参数 | 说明 |
|------|------|
| `DISCORD_BOT_TOKEN` | Bot Token |

**飞书 (Feishu/Lark):**

| 参数 | 说明 |
|------|------|
| `FEISHU_APP_ID` | 应用 App ID（从[飞书开放平台](https://open.feishu.cn/app)获取） |
| `FEISHU_APP_SECRET` | 应用 App Secret |
| `FEISHU_VERIFICATION_TOKEN` | 事件订阅验证 Token（可选） |
| `FEISHU_ENCRYPT_KEY` | 事件加密密钥（可选） |

**WhatsApp:**

| 参数 | 说明 |
|------|------|
| `WHATSAPP_API_TOKEN` | API Token |
| `WHATSAPP_PHONE_NUMBER_ID` | 手机号 ID |
| `WHATSAPP_VERIFY_TOKEN` | Webhook 验证 Token |

**Signal:**

| 参数 | 说明 |
|------|------|
| `SIGNAL_API_URL` | Signal API 地址 |
| `SIGNAL_PHONE_NUMBER` | 手机号 |

安装渠道依赖：

```bash
# 使用 anexus CLI（推荐）
anexus install channel telegram
anexus install channel slack
anexus install channel discord
anexus install channel feishu
anexus install channel all        # 安装全部渠道

# 或直接使用 pip
pip install -e ".[telegram]"
pip install -e ".[all-channels]"
```

## API

### 基础端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/metrics` | GET | 服务指标 |
| `/chat/stream` | POST | 默认用户流式聊天 |
| `/chat/stream/{exec_user}` | POST | 指定执行用户流式聊天 |
| `/agui/test` | GET | AG-UI SSE 测试端点 |
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
    "provider": "gemini"
  }'
```

### Legacy 最简请求（自动转 AG-UI）

```bash
curl --no-buffer -X POST http://localhost:8081/chat/stream/ubuntu \
  -H "Content-Type: application/json" \
  -d '{"user": "test", "content": "你好", "provider": "claude"}'
```

> Provider 也可通过 `X-Provider` 请求头、`provider` 查询参数或请求体中的 `provider` 字段指定；也支持通过查询参数传 `alias`，例如 `/chat/stream/{exec_user}?provider=gemini` 或 `/chat/stream/{exec_user}?alias=gemini-internal`。查询参数会覆盖请求体中的 provider/alias。

## Nexus Web UI

访问地址：`http://localhost:8081/nexus/`

### 会话 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/nexus/sessions` | GET | 会话列表（分页/搜索/状态筛选） |
| `/api/nexus/sessions/{id}` | GET | 会话详情 |
| `/api/nexus/sessions/{id}/messages` | GET | 会话消息 + 工具调用 |
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

### 任务创建模式

- **单任务** — 创建一条任务
- **批量创建** — 一行一个任务，互不依赖
- **任务链** — 一行一个任务，后一个依赖前一个

## 项目结构

```
├── .env.example                 # 配置模板
├── src/
│   ├── server/                  # FastAPI 服务（路由/服务/适配器/模型）
│   ├── runtime/                 # 运行时核心（事件/适配器/存储/执行流）
│   ├── core/                    # 核心业务逻辑（归档/命令/模型/任务）
│   ├── protocols/               # 协议层（AG-UI、基类）
│   ├── providers/               # Provider 实现（Claude/Gemini/Codex/CodeBuddy）
│   │   └── runtime/             # Provider 运行时抽象与注册
│   ├── channels/                # 消息渠道（Telegram/Slack/Discord/飞书/WhatsApp/Signal）
│   └── server/static/nexus/     # Nexus Web UI 静态文件
├── scripts/                     # 启停/测试/部署脚本
├── config/                      # 配置文件
├── examples/                    # 示例代码
└── tests/                       # 单元测试与集成测试
```

## 测试

```bash
# 运行全部测试
./scripts/test.sh

# 仅单元测试
./scripts/test.sh unit

# 带覆盖率报告
./scripts/test.sh coverage
```

## License

MIT
