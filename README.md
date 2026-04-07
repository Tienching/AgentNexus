# Agent Runtime SDK

[中文文档 (Chinese Documentation)](./README_CN.md)

A multi-provider agent runtime that wraps CLI-based AI providers (Claude, Gemini, Codex, etc.) into an HTTP service with **AG-UI SSE** streaming, built-in session/task management, and multi-channel integrations.

## Features

- **AG-UI Protocol First** — Unified AG-UI event stream output for all providers
- **Legacy Compatible** — Accepts minimal `{user, content}` requests; backend auto-converts to AG-UI
- **Multi-Provider** — Claude / Gemini / Codex / CodeBuddy and their `-internal` variants
- **Multi-User Isolation** — Directory isolation by `exec_user + session_id`
- **Nexus Web UI** — Session replay + Task board + File browser
- **Task System** — Single task / bulk create / dependency chains with concurrency control
- **Multi-Channel** — Telegram, Slack, Discord, Feishu (Lark), WhatsApp, Signal integrations
- **CLI Tool (`anexus`)** — Onboard wizard, init, install, start, stop, status, config, list subcommands
- **Systemd Ready** — Includes `.service` file for production deployment

## Requirements

- Python 3.11+
- Redis
- [`uv`](https://github.com/astral-sh/uv) (recommended)
- Corresponding provider CLI (e.g., `claude`, `gemini`, `codex`)

## Quick Start

### Installation

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and install dependencies
git clone <repository-url>
cd <project-directory>
uv sync
```

Choose one setup path before starting the service:

```bash
# Guided setup (recommended)
anexus onboard

# Minimal bootstrap (creates directories and .env)
anexus init
```

Before `anexus start`, make sure Redis is reachable and your selected provider CLI
is installed and authenticated.

### Onboard (Recommended for First-Time Setup)

```bash
anexus onboard
```

The interactive wizard walks you through **6 steps**:

1. **Environment check** — Creates directories and `.env` file
2. **Core config** — API host, port, execution user
3. **Provider selection** — Choose default provider (CodeBuddy / Claude / Gemini / Codex)
4. **Channel selection** — Multi-select channels (Telegram, Slack, Discord, Feishu, WhatsApp, Signal) with guided token input
5. **Dependency install** — Auto-installs selected channel dependencies
6. **Service launch** — Start in foreground or daemon mode

Options: `--reset` (reset .env), `--skip-install`, `--skip-start`

### Manual Setup

```bash
# Configure environment manually
cp .env.example .env
# Edit .env with your settings
```

Minimum fields to review on first boot:

- `EXEC_USER` must match a real Linux user that can run provider CLIs.
- `REDIS_HOST` / `REDIS_PORT` must point at a reachable Redis instance.
- `DEFAULT_PROVIDER` and `CLI_COMMAND` should match an installed provider CLI.

### Running with `anexus` CLI

```bash
# Initialize project (create .env, directories)
anexus init

# Install channel dependencies
anexus install channel telegram
anexus install channel discord
anexus install channel feishu
anexus install channel all        # Install all channels

# Start service (foreground)
anexus start

# Start service (daemon mode)
anexus start --daemon

# Check service status
anexus status

# Stop service
anexus stop

# Interactive config wizard
anexus config wizard

# List installed plugins
anexus list

# Verify runtime health after startup
anexus status --health
```

### Running with Scripts (Alternative)

```bash
./scripts/run.sh                  # Foreground (dev, hot-reload)
./scripts/run-background.sh       # Background (daemon)
./scripts/status.sh               # Check status
./scripts/stop.sh                 # Stop service
```

## Setup Troubleshooting

- `uv: command not found`: install `uv` first, then rerun `uv sync`.
- `Redis connection refused` or health-check failures: start Redis locally or update `REDIS_HOST` / `REDIS_PORT` in `.env`, then rerun `anexus status --health`.
- `provider command not found`: install the CLI named by `CLI_COMMAND` and complete its login/auth flow before starting new tasks.
- Channel import or token errors: install the matching extra with `anexus install channel <name>`, then update the relevant `*_TOKEN` values in `.env`.
- Setup becomes inconsistent: rerun `anexus onboard --reset` for the guided flow, or `anexus init --force` to regenerate `.env` from `.env.example`.

## Configuration

Copy `.env.example` to `.env` and customize as needed:

```bash
cp .env.example .env
```

### Server

| Parameter | Default | Description |
|-----------|---------|-------------|
| `API_HOST` | `0.0.0.0` | Listen address |
| `API_PORT` | `8081` | Listen port |
| `API_WORKERS` | `1` | Worker processes |
| `ENVIRONMENT` | `development` | Runtime environment |
| `DEBUG` | `false` | Debug mode |

### Logging

| Parameter | Default | Description |
|-----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Log level |
| `LOG_DIR` | `./logs` | Log directory |
| `LOG_MAX_BYTES` | `10485760` | Max log file size (bytes) |
| `LOG_BACKUP_COUNT` | `5` | Log backup count |

### User Directory

| Parameter | Default | Description |
|-----------|---------|-------------|
| `USER_HOME_BASE` | `/home` | User home base path |
| `AUTO_CREATE_USER_DIR` | `true` | Auto-create user directories |
| `EXEC_USER` | `ubuntu` | Default execution user (Linux username) |

### Redis

| Parameter | Default | Description |
|-----------|---------|-------------|
| `REDIS_HOST` | `localhost` | Redis host |
| `REDIS_PORT` | `6379` | Redis port |
| `REDIS_DB` | `0` | Redis database |
| `REDIS_PASSWORD` | | Redis password |
| `REDIS_KEY_PREFIX` | `aona:` | Redis key prefix |

### Provider

| Parameter | Default | Description |
|-----------|---------|-------------|
| `CLI_COMMAND` | `claude` | Default CLI command |
| `CLI_TIMEOUT` | `120` | CLI execution timeout (seconds) |
| `GEMINI_COMMAND` | `gemini` | Gemini CLI command |
| `DEFAULT_PROVIDER` | `codebuddy` | Default provider |
| `DEFAULT_ALIAS` | | Default provider alias |

### Streaming

| Parameter | Default | Description |
|-----------|---------|-------------|
| `STREAM_CHUNK_SIZE` | `100` | Characters per chunk |
| `STREAM_DELAY_MS` | `50` | Delay between chunks (ms) |
| `STREAM_BUFFER_SIZE` | `1000` | Stream buffer size |

### Task Executor

| Parameter | Default | Description |
|-----------|---------|-------------|
| `EXECUTOR_ENABLED` | `true` | Enable task executor |
| `EXECUTOR_DEFAULT_MAX_CONCURRENCY` | `3` | Max concurrent tasks |

### Nexus Web UI

| Parameter | Default | Description |
|-----------|---------|-------------|
| `NEXUS_PASSWORD` | | UI password (empty = no auth) |
| `NEXUS_SESSION_TTL` | `86400` | Session TTL (seconds) |

### Channels (Messaging)

Enable messaging channels by configuring these environment variables:

**Telegram:**

| Parameter | Description |
|-----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Bot token (from @BotFather) |
| `TELEGRAM_ALLOWED_USERS` | Allowed user IDs (comma-separated, empty = allow all) |

**Slack:**

| Parameter | Description |
|-----------|-------------|
| `SLACK_BOT_TOKEN` | Bot OAuth Token (xoxb-) |
| `SLACK_APP_TOKEN` | App Token for Socket Mode (xapp-) |

**Discord:**

| Parameter | Description |
|-----------|-------------|
| `DISCORD_BOT_TOKEN` | Bot token |

**Feishu (Lark):**

| Parameter | Description |
|-----------|-------------|
| `FEISHU_APP_ID` | App ID (from [Feishu Open Platform](https://open.feishu.cn/app)) |
| `FEISHU_APP_SECRET` | App Secret |
| `FEISHU_VERIFICATION_TOKEN` | Event subscription verification token (optional) |
| `FEISHU_ENCRYPT_KEY` | Event encryption key (optional) |

**WhatsApp:**

| Parameter | Description |
|-----------|-------------|
| `WHATSAPP_API_TOKEN` | API token |
| `WHATSAPP_PHONE_NUMBER_ID` | Phone number ID |
| `WHATSAPP_VERIFY_TOKEN` | Webhook verify token |

**Signal:**

| Parameter | Description |
|-----------|-------------|
| `SIGNAL_API_URL` | Signal API URL |
| `SIGNAL_PHONE_NUMBER` | Phone number |

Install channel dependencies:

```bash
# Using anexus CLI (recommended)
anexus install channel telegram
anexus install channel slack
anexus install channel discord
anexus install channel feishu
anexus install channel all        # All channels

# Or using pip directly
pip install -e ".[telegram]"
pip install -e ".[all-channels]"
```

## API

### Core Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/metrics` | GET | Service metrics |
| `/chat/stream` | POST | Stream chat (default user) |
| `/chat/stream/{exec_user}` | POST | Stream chat (specified user) |
| `/agui/test` | GET | AG-UI SSE test endpoint |
| `/nexus/` | GET | Nexus Web UI |

### AG-UI Request (Recommended)

```bash
curl --no-buffer -X POST http://localhost:8081/chat/stream/ubuntu \
  -H "Content-Type: application/json" \
  -d '{
    "threadId": "thread-123",
    "runId": "run-456",
    "messages": [{"id": "msg-1", "role": "user", "content": "Hello"}],
    "forwardedProps": {"username": "test"},
    "provider": "gemini"
  }'
```

### Legacy Request (Auto-converts to AG-UI)

```bash
curl --no-buffer -X POST http://localhost:8081/chat/stream/ubuntu \
  -H "Content-Type: application/json" \
  -d '{"user": "test", "content": "Hello", "provider": "claude"}'
```

> Provider can also be specified via the `X-Provider` header, the `provider` query param, or the `provider` field in the body. You can also pass `alias` as a query param, for example `/chat/stream/{exec_user}?provider=gemini` or `/chat/stream/{exec_user}?alias=gemini-internal`. Query params override request-body `provider`/`alias` values.

## Nexus Web UI

Access at: `http://localhost:8081/nexus/`

### Session API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/nexus/sessions` | GET | List sessions (paginated, searchable) |
| `/api/nexus/sessions/{id}` | GET | Session details |
| `/api/nexus/sessions/{id}/messages` | GET | Session messages + tool calls |
| `/api/nexus/sessions/{id}/cancel` | POST | Cancel session |
| `/api/nexus/sessions/{id}` | DELETE | Delete session |
| `/api/nexus/sessions/bulk_delete` | POST | Bulk delete sessions |
| `/api/nexus/usernames` | GET | Username list |
| `/api/nexus/agents` | GET | Available agents |

### Task API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/nexus/tasks` | GET | List tasks |
| `/api/nexus/tasks` | POST | Create task |
| `/api/nexus/tasks/bulk` | POST | Bulk create tasks |
| `/api/nexus/tasks/{id}` | GET | Task details |
| `/api/nexus/tasks/{id}` | DELETE | Delete task |
| `/api/nexus/tasks/{id}/status` | PATCH | Update task status |
| `/api/nexus/tasks/bulk_archive` | POST | Bulk archive |
| `/api/nexus/tasks/bulk_unarchive` | POST | Bulk unarchive |
| `/api/nexus/tasks/bulk_clear` | POST | Clear archived tasks |
| `/api/nexus/tasks/bulk_delete` | POST | Force bulk delete |
| `/api/nexus/tasks/{id}/agui/messages` | GET | Task conversation snapshot |
| `/api/nexus/tasks/{id}/agui/stream` | GET | Task conversation SSE replay |

### Task Creation Modes

- **Single Task** — Create one task
- **Bulk Create** — One task per line, independent
- **Task Chain** — One task per line, each depends on the previous

## Project Structure

```
├── .env.example                 # Configuration template
├── src/
│   ├── server/                  # FastAPI service (routers, services, adapters, models)
│   ├── runtime/                 # Runtime core (events, adapters, stores, execution)
│   ├── core/                    # Core business logic (archiving, commands, models, tasks)
│   ├── protocols/               # Protocol layer (AG-UI, base)
│   ├── providers/               # Provider implementations (Claude, Gemini, Codex, CodeBuddy)
│   │   └── runtime/             # Provider runtime abstraction and registry
│   ├── channels/                # Messaging channels (Telegram, Slack, Discord, Feishu, WhatsApp, Signal)
│   └── server/static/nexus/     # Nexus Web UI static files
├── scripts/                     # Run, stop, status, test, deploy scripts
├── config/                      # Configuration files
├── examples/                    # Example code
└── tests/                       # Unit and integration tests
```

## Testing

```bash
# Run all tests
./scripts/test.sh

# Unit tests only
./scripts/test.sh unit

# With coverage report
./scripts/test.sh coverage
```

## License

MIT
