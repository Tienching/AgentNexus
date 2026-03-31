# Nanobot 源码合入 Agent-Nexus 设计文档

**Date**: 2026-03-31
**Status**: Approved
**Scope**: 将 nanobot 引擎源码合入 agent-nexus，使其成为默认 Chat Provider

---

## 1. 目标

将 nanobot 的 AgentLoop 引擎源码直接合入 agent-nexus 仓库（不作为外部依赖），成为默认的聊天引擎。用户发消息时不再启动 claude CLI 子进程，而是进程内调用 AgentLoop。orchestrator/mission skill 自动加载，用户通过自然语言即可安排任务。

## 2. 代码布局

### 2.1 复制范围

从 `~/Projects/nanobot/nanobot/` 复制到 `agent-nexus/src/nanobot/`。

**包含** (核心运行时):
- `agent/` — AgentLoop, ContextBuilder, SkillsLoader, Tools (read_file, write_file, exec, web, spawn, mission, mcp, cron, message)
- `bus/` — MessageBus (进程内异步消息队列)
- `config/` — Config schema + loader (pydantic-settings based)
- `mission/` — Mission decomposition & DAG scheduling
- `providers/` — LLM Provider 抽象 (OpenAI / Anthropic / etc)
- `session/` — Session manager (文件持久化)
- `command/` — nanobot 内置 slash commands (/help, /model, /stop, etc)
- `cron/` — Cron service
- `skills/` — Built-in skills (memory, etc)
- `utils/` — Helpers (strip_think, token counting, etc)
- `__init__.py`

**排除** (agent-nexus 已有对应实现):
- `channels/` — agent-nexus 有自己的 channel 层 (Telegram/Slack/WeChat/etc)
- `cli/` — agent-nexus 有自己的 CLI 和 REST API
- `gateway/` — agent-nexus 有自己的 HTTP server
- `heartbeat/` — 不需要
- `security/` — 不需要 (agent-nexus 有自己的认证)
- `templates/` — 不需要

### 2.2 Import 路径改写

所有复制进来的文件中 `from nanobot.xxx` → `from src.nanobot.xxx`，`import nanobot.xxx` → `import src.nanobot.xxx`。

使用 sed 批量替换 (~65 个文件):
```bash
find src/nanobot -name "*.py" -exec sed -i 's/from nanobot\./from src.nanobot./g' {} +
find src/nanobot -name "*.py" -exec sed -i 's/import nanobot\./import src.nanobot./g' {} +
# 也替换字符串中的引用 (如 "nanobot.xxx" 模块路径)
find src/nanobot -name "*.py" -exec sed -i 's/"nanobot\./"src.nanobot./g' {} +
```

替换后用 `grep -rn "from nanobot\." src/nanobot/` 验证无遗漏。

### 2.3 最终目录结构

```
agent-nexus/
├── src/
│   ├── nanobot/                     ← nanobot 引擎源码
│   │   ├── agent/
│   │   │   ├── loop.py              # AgentLoop (核心)
│   │   │   ├── context.py           # ContextBuilder (系统 prompt)
│   │   │   ├── skills.py            # SkillsLoader (技能发现)
│   │   │   ├── memory.py            # MemoryConsolidator
│   │   │   ├── subagent.py          # SubagentManager
│   │   │   └── tools/               # 内置工具集
│   │   ├── bus/                     # MessageBus
│   │   ├── config/                  # Config
│   │   ├── mission/                 # Mission system
│   │   ├── providers/               # LLM Providers
│   │   ├── session/                 # Session
│   │   ├── command/                 # nanobot slash commands
│   │   ├── cron/                    # Cron
│   │   ├── skills/                  # Built-in skills
│   │   └── utils/                   # Helpers
│   ├── providers/
│   │   ├── nanobot/                 ← NanobotExecutor (桥接层)
│   │   │   ├── executor.py
│   │   │   ├── adapter.py
│   │   │   ├── event_schema.py
│   │   │   └── session_bridge.py
│   │   ├── claude/
│   │   ├── gemini/
│   │   ├── codex/
│   │   └── codebuddy/
│   ├── runtime/
│   │   └── adapters/
│   │       └── nanobot/             ← AG-UI adapter
│   └── server/
├── prompts/
│   └── skills/
│       ├── orchestrator/            ← 注入到 nanobot 的技能
│       └── mission/                 ← 注入到 nanobot 的技能
└── tests/
    └── providers/
        └── nanobot/                 ← 测试
```

## 3. 关键接口修复

### 3.1 NanobotExecutor.execute() 签名

**问题**: StreamOrchestrator 调用 `executor.execute(request_model, exec_user=exec_user, output_format="raw")`，但当前签名是 `(context: RequestContext, output_format="raw")`。

**修复**: 改为匹配所有其他 executor 的签名：

```python
async def execute(
    self,
    request: Any,              # RequestModel from StreamHandler
    exec_user: str = "default",
    output_format: str = "raw",
) -> AsyncGenerator[str, None]:
    # 从 RequestModel 提取字段
    content = getattr(request, 'content', '') or ''
    session_id = getattr(request, 'session_id', 'default') or 'default'
    cwd = getattr(request, 'cwd', None)
    model = getattr(request, 'model', None)
    # ... 调用 AgentLoop.process_direct()
```

### 3.2 BaseExecutor._build_command() 兼容

NanobotExecutor 不使用子进程，`_build_command()` 返回空列表。这是合法的——该方法只在 CLI 子进程 executor 中使用。

## 4. Skill 注入机制

### 4.1 SkillsLoader 增加 extra_skills_dirs

修改 `src/nanobot/agent/skills.py`，`SkillsLoader.__init__` 增加 `extra_skills_dirs` 参数：

```python
class SkillsLoader:
    def __init__(self, workspace: Path, builtin_skills_dir=None, extra_skills_dirs=None):
        self.workspace = workspace
        self.workspace_skills = workspace / "skills"
        self.builtin_skills = builtin_skills_dir or BUILTIN_SKILLS_DIR
        self.extra_skills_dirs = extra_skills_dirs or []

    def list_skills(self, filter_unavailable=True):
        skills = []
        # 1. Workspace skills (最高优先)
        if self.workspace_skills.exists(): ...
        # 2. Extra skills dirs (新增)
        for extra_dir in self.extra_skills_dirs:
            if extra_dir.exists():
                for skill_dir in extra_dir.iterdir():
                    if skill_dir.is_dir():
                        skill_file = skill_dir / "SKILL.md"
                        if skill_file.exists() and not any(s["name"] == skill_dir.name for s in skills):
                            skills.append({"name": skill_dir.name, "path": str(skill_file), "source": "extra"})
        # 3. Built-in skills (最低优先)
        if self.builtin_skills and self.builtin_skills.exists(): ...
        return skills
```

### 4.2 NanobotExecutor 注入路径

在 `_NanobotPool._create_loop()` 中，AgentLoop 创建后注入 nexus skills 路径：

```python
nexus_skills_dir = Path(__file__).resolve().parents[3] / "prompts" / "skills"
if nexus_skills_dir.exists():
    loop.context.skills.extra_skills_dirs = [nexus_skills_dir]
```

### 4.3 效果

- `prompts/skills/orchestrator/SKILL.md` 出现在 nanobot 技能列表
- `prompts/skills/mission/SKILL.md` 出现在 nanobot 技能列表
- Agent 可以自主 `read_file` 加载完整技能内容
- 用户说"帮我创建一个任务分析代码" → nanobot 读取 orchestrator skill → 执行 `python3 prompts/skills/orchestrator/scripts/orchestrator.py create ...`

## 5. 默认 Provider 切换

### 5.1 dispatcher.py

```python
def _default_provider() -> str:
    import os
    return os.environ.get("AGENT_NEXUS_DEFAULT_PROVIDER", "nanobot")
```

### 5.2 安全回退

| 方式 | 用法 |
|------|------|
| 环境变量 | `AGENT_NEXUS_DEFAULT_PROVIDER=claude` |
| 请求参数 | `?provider=claude` |
| Slash 命令 | `/switch claude` |
| Session 级别 | Redis 中存储的 workspace_provider |

### 5.3 Slash command 路由

保持现有逻辑不变：`content.startswith("/")` → 走 claude executor。
nanobot executor 只处理普通聊天消息。

## 6. 依赖合并

将 nanobot 核心运行时依赖合入 `pyproject.toml`：

| 依赖 | 用途 | 是否已有 |
|------|------|---------|
| `openai>=2.8.0` | LLM 调用 | 需新增 |
| `tiktoken>=0.12.0` | Token 计数 | 需新增 |
| `loguru>=0.7.3` | nanobot 日志 | 需新增 |
| `mcp>=1.26.0` | MCP server 集成 | 需新增 |
| `croniter>=6.0.0` | Cron 表达式 | 需新增 |
| `json-repair>=0.57.0` | 容错 JSON | 需新增 |
| `chardet>=3.0.2` | 编码检测 | 需新增 |
| `ddgs>=9.5.5` | DuckDuckGo 搜索 | 需新增 |
| `readability-lxml>=0.8.4` | 网页内容提取 | 需新增 |
| `anthropic>=0.45.0` | Anthropic SDK | 已有 |
| `pydantic>=2.12.0` | 数据模型 | 已有 |
| `pydantic-settings>=2.12.0` | Settings | 已有 |
| `httpx>=0.28.0` | HTTP client | 已有 |
| `rich>=14.0.0` | 终端格式化 | 已有 |
| `websockets>=16.0` | WebSocket | 已有 |

## 7. 数据流

```
HTTP POST /chat/stream/{exec_user}
    │
    ▼
StreamHandler.handle_agui_request()
    │ 解析 provider → "nanobot" (默认)
    │ 构造 RequestModel
    │
    ▼
StreamOrchestrator.stream_agui()
    │ executor.execute(request_model, exec_user, "raw")
    │
    ▼
NanobotExecutor.execute()
    │ 从 RequestModel 提取 content, session_id, cwd
    │ _NanobotPool.get_or_create(workspace) → AgentLoop 单例
    │ 构建 callback → asyncio.Queue 桥接
    │ asyncio.create_task(AgentLoop.process_direct(...))
    │
    ▼
AgentLoop._run_agent_loop()
    │ 构建 system prompt (含 orchestrator/mission skill)
    │ 调用 LLM (OpenAI/Anthropic API)
    │ 执行 tool calls (read_file, exec, web_search, ...)
    │ 通过 on_stream/on_tool_start/on_tool_end 回调推送事件
    │
    ▼
asyncio.Queue → yield JSON lines
    │ {"type": "text_delta", "delta": "..."}
    │ {"type": "tool_start", "name": "exec", ...}
    │
    ▼
NanobotAGUIAdapter.convert()
    │ text_delta → TEXT_MESSAGE_CONTENT
    │ tool_start → TOOL_CALL_START + TOOL_CALL_ARGS
    │
    ▼
SSE Response → Client
    data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"msg-001","delta":"Hello"}
```

## 8. 实施步骤

### Phase 1: 源码复制 + Import 改写
1. 复制 nanobot 核心目录到 `src/nanobot/`
2. 批量替换 import 路径
3. 验证 `python3 -c "from src.nanobot.agent.loop import AgentLoop"` 通过

### Phase 2: NanobotExecutor 签名修复
1. 修改 `execute()` 为 3 参数签名
2. 更新测试

### Phase 3: SkillsLoader 增加 extra_skills_dirs
1. 修改 `src/nanobot/agent/skills.py`
2. 修改 `_NanobotPool._create_loop()` 注入 nexus skills 路径

### Phase 4: 默认 Provider 切换
1. `_default_provider()` 改为 "nanobot"
2. 更新受影响的测试

### Phase 5: 依赖合并
1. 更新 `pyproject.toml`
2. `uv sync` 或 `pip install -e .`

### Phase 6: 端到端验证
1. 导入测试
2. 单元测试
3. 启动服务 + curl 测试
4. `/switch claude` 回退测试

## 9. 风险与缓解

| 风险 | 概率 | 缓解 |
|------|------|------|
| Import 替换遗漏 | 中 | sed 替换后用 `python3 -c "import src.nanobot"` 验证 |
| 循环依赖 | 低 | nanobot 不依赖 agent-nexus 代码，单向依赖 |
| nanobot 依赖冲突 | 低 | 版本约束已检查，无冲突 |
| 排除目录导致缺失 | 中 | 复制后立即跑 import 测试，缺什么补什么 |
| LLM API key 配置 | 低 | nanobot 读 `~/.nanobot/config.json` 或环境变量 |
