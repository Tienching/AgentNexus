# Design: NexusHub-Style Web Viewer

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI Application                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────────────┐   │
│  │ /chat/stream│   │ /api/nexus/ │   │ /nexus/ (Static)    │   │
│  │  (AGUI SSE) │   │  (REST API) │   │  (Web UI)           │   │
│  └──────┬──────┘   └──────┬──────┘   └─────────────────────┘   │
│         │                 │                                     │
│         ▼                 ▼                                     │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              Session Storage Service                     │   │
│  │  - save_session_meta()   - get_session_messages()       │   │
│  │  - add_session_message() - search_sessions()            │   │
│  │  - save_tool_call()      - delete_session()             │   │
│  └──────────────────────────┬──────────────────────────────┘   │
│                             │                                   │
│                             ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    RedisClient                           │   │
│  │              (Existing, with aona: prefix)               │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Component Design

### 1. Session Storage Service (`services/session_storage.py`)

负责会话数据的 CRUD 操作，复用现有 `RedisClient`。

#### Data Models

```python
class SessionStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"

class SessionMeta(BaseModel):
    id: str
    thread_id: str
    run_id: Optional[str] = None
    title: str
    username: str
    exec_user: Optional[str] = None
    created_at: int  # Unix timestamp ms
    updated_at: int
    message_count: int = 0
    status: SessionStatus = SessionStatus.IDLE

class StoredMessage(BaseModel):
    id: str
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: int
    status: Literal["pending", "streaming", "complete", "error"]
    tool_call_ids: Optional[List[str]] = None

class StoredToolCall(BaseModel):
    id: str
    tool_name: str
    args: Dict[str, Any]
    args_string: str
    status: Literal["pending", "executing", "completed", "failed"]
    result: Optional[Any] = None
    error: Optional[str] = None
    start_time: int
    end_time: Optional[int] = None
    parent_message_id: Optional[str] = None
```

#### Redis Key Patterns

| Key Pattern | Type | Description | TTL |
|-------------|------|-------------|-----|
| `session:{id}:meta` | Hash | 会话元信息 | 7 days |
| `session:{id}:messages` | List | 消息列表 (JSON strings) | 7 days |
| `session:{id}:toolcalls` | Hash | 工具调用 (id -> JSON) | 7 days |
| `session:{id}:msg:{msgId}:content` | String | 流式内容临时存储 | 1 hour |
| `user:{username}:sessions` | Sorted Set | 用户会话索引 (score=updatedAt) | No TTL |

### 2. Stream Archiver (`services/stream_archiver.py`)

在 AGUI Stream 处理过程中，将事件归档到 Redis。

#### Integration Point

在 `StreamHandler.handle_agui_request()` 的 `generate_agui()` 生成器中：

```python
async def generate_agui():
    archiver = StreamArchiver(session_id, thread_id, run_id, username)
    
    try:
        start_event = adapter.create_start_event()
        if start_event:
            await archiver.on_run_started()
            yield start_event
        
        async for line in self.executor.execute(...):
            event_data = json.loads(line)
            converted = adapter.convert(event_data)
            
            # Archive event (non-blocking)
            asyncio.create_task(archiver.archive_event(event_data))
            
            if converted:
                yield converted
        
        end_event = adapter.create_end_event()
        if end_event:
            await archiver.on_run_finished()
            yield end_event
            
    except Exception as e:
        await archiver.on_run_error(str(e))
        raise
```

### 3. Web API Router (`routers/nexus.py`)

提供 REST API 供 Web UI 调用。

#### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/nexus/sessions` | 获取会话列表（支持分页、搜索） |
| GET | `/api/nexus/sessions/{id}` | 获取会话详情 |
| GET | `/api/nexus/sessions/{id}/messages` | 获取会话消息 |
| DELETE | `/api/nexus/sessions/{id}` | 删除会话 |
| POST | `/api/nexus/sessions/{id}/cancel` | 取消运行中的会话 |

#### Query Parameters

- `username`: 用户名（必需）
- `page`: 页码（默认 1）
- `page_size`: 每页数量（默认 20，最大 100）
- `search`: 搜索关键词（标题模糊匹配）
- `status`: 状态过滤

### 4. Web UI (`static/nexus/`)

纯前端单页应用，使用 Tailwind CSS 样式。

#### File Structure

```
src/claude_code_api/static/nexus/
├── index.html          # 主页面（会话列表）
├── session.html        # 会话详情页
├── css/
│   └── styles.css      # 自定义样式
└── js/
    ├── api.js          # API 调用封装
    ├── app.js          # 主应用逻辑
    └── components.js   # UI 组件
```

#### Features

1. **会话列表页**
   - 按时间分组显示（今天、昨天、本周等）
   - 搜索框实时过滤
   - 状态标签（Running/Completed/Error）
   - 点击进入详情

2. **会话详情页**
   - 消息列表展示
   - 工具调用折叠显示
   - Markdown 渲染
   - 代码高亮

## Chrome 验证流程

### 测试步骤

1. **启动服务**
   ```bash
   cd /tmp/virtual-human-sdk-feature-nexushub
   python -m uvicorn src.claude_code_api.app:app --reload --port 8081
   ```

2. **发送 AGUI 请求**
   ```bash
   curl -X POST http://localhost:8081/chat/stream/test \
     -H "Content-Type: application/json" \
     -d '{
       "threadId": "test-thread-1",
       "runId": "test-run-1",
       "messages": [{"id": "msg-1", "role": "user", "content": "Hello"}],
       "forwardedProps": {"username": "testuser"}
     }'
   ```

3. **打开 Web UI**
   - 访问 `http://localhost:8081/nexus/`
   - 应看到刚创建的会话

4. **验证功能**
   - 搜索会话
   - 点击查看详情
   - 检查消息内容
   - 使用 DevTools Network 面板验证 API 调用

### 验收标准

- [ ] 会话列表正确显示
- [ ] 搜索功能正常
- [ ] 详情页消息完整
- [ ] 工具调用正确展示
- [ ] 无 JavaScript 控制台错误
- [ ] API 响应时间 < 200ms
