# Agent-Nexus Codebase Structure - Nexus Provider Integration Guide

## Executive Summary
The agent-nexus codebase follows a clean provider architecture with **two main layers**:
1. **Provider Layer** (`src/providers/`): CLI subprocess executors specific to each provider
2. **Runtime Layer** (`src/runtime/adapters/`): Protocol adapters that transform provider events to AG-UI format

To integrate Nexus, we need to:
- Create `src/providers/nexus/` with executor + config
- Create `src/runtime/adapters/nexus/` with AG-UI adapter
- Update `src/providers/dispatcher.py` to register the provider
- Update `src/server/config.py` with nexus configuration options

---

## 1. DIRECTORY STRUCTURE

```
src/providers/
├── base.py                          # BaseExecutor, ExecutorConfig, RequestContext (abstract)
├── dispatcher.py                    # Provider factory + registry
├── __init__.py
├── claude/                          # Claude provider (pattern to follow)
│   ├── executor.py                  # CLIExecutor(BaseExecutor)
│   ├── adapter.py                   # [DEPRECATED - moved to runtime]
│   └── __init__.py
├── codebuddy/
│   ├── cli_executor.py              # CodebuddyCLIExecutor(BaseExecutor)
│   └── __init__.py
├── codex/
│   ├── cli_executor.py              # CodexCLIExecutor(BaseExecutor)
│   ├── executor.py                  # CodexExecutor [Legacy MCP]
│   ├── connection.py
│   └── __init__.py
├── gemini/
│   ├── executor.py                  # GeminiExecutor(BaseExecutor)
│   └── __init__.py
├── persistent/                      # Persistent process management
│   ├── process_manager.py
│   └── __init__.py
├── runtime/                         # Shared runtime infrastructure
└── [NEEDS CREATION] nexus/        # Where you'll add nexus provider

src/runtime/adapters/
├── base.py                          # BaseAdapter, AdapterState, ProtocolType
├── __init__.py
├── claude/
│   ├── agui_adapter.py              # AGUIAdapter(BaseAdapter)
│   └── __init__.py
├── codebuddy/
│   ├── agui_adapter.py              # CodebuddyAGUIAdapter(BaseAdapter)
│   └── __init__.py
├── codex/
│   ├── cli_agui_adapter.py          # CodexCLIAGUIAdapter(BaseAdapter) [Recommended]
│   ├── agui_adapter.py              # CodexAGUIAdapter [Legacy]
│   └── __init__.py
├── gemini/
│   ├── agui_adapter.py              # GeminiAGUIAdapter(BaseAdapter)
│   └── __init__.py
└── [NEEDS CREATION] nexus/        # Where you'll add nexus adapter
```

---

## 2. PROVIDER LAYER: EXECUTOR ARCHITECTURE

### BaseExecutor (src/providers/base.py)

**Base class for all executors:**
```python
class BaseExecutor(ABC):
    def __init__(self, config: Optional[ExecutorConfig] = None):
        self.config = config or ExecutorConfig()
    
    @abstractmethod
    async def execute(
        self,
        context: RequestContext,
        output_format: str = "raw",
    ) -> AsyncGenerator[str, None]:
        """Execute CLI and yield stream output.
        
        Args:
            context: Unified request context
            output_format: "raw" (JSON lines) or "legacy" (event:delta SSE)
            
        Yields:
            Output lines (JSON format)
        """
        pass
    
    @abstractmethod
    def _build_command(self, context: RequestContext) -> List[str]:
        """Build the CLI command to execute."""
        pass
```

### RequestContext (src/providers/base.py)

**Unified input context (replaces tight coupling to RequestModel):**
```python
@dataclass
class RequestContext:
    content: str                           # User input
    user: str = "anonymous"                # API user
    session_id: str = "default"            # Session ID
    exec_user: str = "default"             # Linux user for su
    cwd: Optional[str] = None              # Working directory
    cwd_mode: str = ""                     # "inplace" or ""
    run_kind: str = ""                     # "chat_continue" etc.
    alias: Optional[str] = None            # CLI command alias
    model: Optional[str] = None            # LLM model override
    cli_session_id: Optional[str] = None   # CLI session UUID
    session_cleared: bool = False          # /clear just executed
    metadata: Dict[str, Any] = field(default_factory=dict)
```

### ExecutorConfig (src/providers/base.py)

**Base executor configuration:**
```python
@dataclass
class ExecutorConfig:
    timeout: float = 600.0
    user_home_base: str = "/home"
    extra: Dict[str, Any] = field(default_factory=dict)
```

### Example: CodebuddyCLIExecutor (src/providers/codebuddy/cli_executor.py)

**Pattern to follow for Nexus:**
```python
class CodebuddyExecutorConfig(ExecutorConfig):
    def __init__(
        self,
        timeout: float = 600.0,
        user_home_base: str = "/home",
        codebuddy_command: str = "codebuddy",
        **kwargs,
    ):
        super().__init__(timeout=timeout, user_home_base=user_home_base)
        self.codebuddy_command = codebuddy_command
        self.extra.update(kwargs)

class CodebuddyCLIExecutor(BaseExecutor):
    def __init__(self, config: Optional[CodebuddyExecutorConfig] = None):
        if config is None:
            super().__init__(CodebuddyExecutorConfig())
            return
        if isinstance(config, CodebuddyExecutorConfig):
            super().__init__(config)
            return
        # Backward-compat: accept server settings-like objects
        super().__init__(
            CodebuddyExecutorConfig(
                timeout=getattr(config, "cli_timeout", 600.0),
                user_home_base=getattr(config, "user_home_base", "/home"),
                codebuddy_command=getattr(config, "codebuddy_command", "codebuddy"),
            )
        )
    
    async def execute(
        self,
        request: Any,
        exec_user: str = "default",
        output_format: str = "raw",
    ) -> AsyncGenerator[str, None]:
        if isinstance(request, RequestContext):
            context = request
        else:
            context = RequestContext.from_request_model(request, exec_user)
        async for line in self._execute_internal(context, output_format=output_format):
            yield line
    
    def _build_command(self, context: RequestContext) -> List[str]:
        # Build command list to execute
        pass
```

---

## 3. RUNTIME ADAPTER LAYER: AG-UI PROTOCOL ADAPTER

### BaseAdapter (src/runtime/adapters/base.py)

**Base class for all adapters:**
```python
class ProtocolType(str, Enum):
    AGUI = "agui"

class AdapterState:
    def __init__(self, thread_id: str, run_id: str):
        self.thread_id = thread_id
        self.run_id = run_id
        self.current_message_id: Optional[str] = None
        self.message_started = False
        self.tool_input_buffer: Dict[int, tuple] = {}
        self.active_tool_calls: Dict[str, str] = {}
        self.run_started = False
        self.run_finished = False
        self.has_error = False

class BaseAdapter(ABC):
    def __init__(self):
        self.state: Optional[AdapterState] = None
    
    def init_state(self, thread_id: str, run_id: str) -> None:
        self.state = AdapterState(thread_id, run_id)
    
    @property
    @abstractmethod
    def protocol_type(self) -> ProtocolType:
        pass
    
    @abstractmethod
    def convert(self, event: Dict[str, Any]) -> Optional[str]:
        """Transform provider event to AG-UI format.
        
        Returns SSE format string or None if event doesn't apply.
        """
        pass
    
    @abstractmethod
    def format_sse(self, data: Any) -> str:
        """Format as AG-UI SSE format."""
        pass
    
    @abstractmethod
    def create_start_event(self) -> Optional[str]:
        """Create run start event."""
        pass
    
    @abstractmethod
    def create_end_event(self, is_error: bool = False, error_msg: str = "") -> str:
        """Create run end event."""
        pass
    
    @abstractmethod
    def create_error_event(self, error_msg: str) -> str:
        """Create error event."""
        pass
    
    async def process_stream(
        self, 
        stream: AsyncGenerator[str, None]
    ) -> AsyncGenerator[str, None]:
        """Process provider stream and yield AG-UI events."""
        start_event = self.create_start_event()
        if start_event:
            yield start_event
        
        async for line in stream:
            if not line.strip():
                continue
            event_data = self.parse_json_line(line)
            if event_data:
                converted = self.convert(event_data)
                if converted:
                    yield converted
        
        end_event = self.create_end_event()
        if end_event:
            yield end_event
```

### Example: CodebuddyAGUIAdapter (src/runtime/adapters/codebuddy/agui_adapter.py)

**Pattern to follow for Nexus:**
```python
class CodebuddyAGUIAdapter(BaseAdapter):
    def __init__(self):
        super().__init__()
        self._reset_tracking_state()
    
    def _reset_tracking_state(self):
        self._in_thinking_block: bool = False
        self._thinking_buffer: str = ""
        self._has_streamed_text_content: bool = False
    
    def init_state(self, thread_id: str, run_id: str) -> None:
        super().init_state(thread_id, run_id)
        self._reset_tracking_state()
    
    @property
    def protocol_type(self) -> ProtocolType:
        return ProtocolType.AGUI
    
    def _generate_message_id(self) -> str:
        return f"codebuddy-msg-{uuid.uuid4().hex}"
    
    def convert(self, event: Dict[str, Any]) -> Optional[str]:
        if not self.state or not isinstance(event, dict):
            return None
        
        event_type = event.get("type")
        
        # Handle different event types:
        if event_type == "init":
            if not self.state.run_started:
                return self.create_start_event()
            return None
        
        if event_type == "error":
            msg = event.get("message") or "Error"
            return self.create_error_event(msg)
        
        # ... more handlers ...
        
        return None
    
    def format_sse(self, data: Any) -> str:
        if hasattr(data, "to_sse"):
            return data.to_sse()
        json_str = json.dumps(data, ensure_ascii=False)
        return f"data: {json_str}\n\n"
    
    def create_start_event(self) -> Optional[str]:
        if not self.state or self.state.run_started:
            return None
        self.state.run_started = True
        event = RunStartedEvent(
            threadId=self.state.thread_id,
            runId=self.state.run_id
        )
        return event.to_sse()
    
    def create_end_event(self, is_error: bool = False, error_msg: str = "") -> str:
        if not self.state:
            return ""
        
        results = []
        if self.state.message_started and self.state.current_message_id:
            msg_end = TextMessageEndEvent(messageId=self.state.current_message_id)
            results.append(msg_end.to_sse())
            self.state.message_started = False
        
        run_finished = RunFinishedEvent(
            threadId=self.state.thread_id,
            runId=self.state.run_id
        )
        results.append(run_finished.to_sse())
        self.state.run_finished = True
        
        return "".join(results)
    
    def create_error_event(self, error_msg: str) -> str:
        if not self.state:
            return ""
        error = RunErrorEvent(
            threadId=self.state.thread_id,
            runId=self.state.run_id,
            message=error_msg
        )
        return error.to_sse()
```

---

## 4. DISPATCHER ARCHITECTURE (src/providers/dispatcher.py)

**Single source of truth for executor + adapter creation:**

```python
def normalize_provider(name: Optional[str]) -> str:
    """Normalize provider name to canonical key."""
    n = (name or "").strip().lower()
    if n in ("gemini", "codex", "codebuddy"):
        return n
    return "claude"  # Default fallback

def create_executor(provider: str, *, config=None):
    """Create executor instance for provider."""
    if config is None:
        from src.server.config import settings as _settings
        config = _settings
    
    key = normalize_provider(provider)
    
    if key == "gemini":
        from src.providers.gemini import GeminiExecutor
        return GeminiExecutor(config=config)
    
    if key == "codex":
        from src.providers.codex import CodexCLIExecutor
        return CodexCLIExecutor(config=config)
    
    if key == "codebuddy":
        from src.providers.codebuddy import CodebuddyCLIExecutor
        return CodebuddyCLIExecutor(config=config)
    
    # Default: Claude
    from src.server.services.cli_executor import CLIExecutor
    return CLIExecutor(config=config)

def create_all_executors(*, config=None) -> dict:
    """Pre-create one executor per known provider."""
    if config is None:
        from src.server.config import settings as _settings
        config = _settings
    
    return {
        "claude":    create_executor("claude", config=config),
        "gemini":    create_executor("gemini", config=config),
        "codex":     create_executor("codex", config=config),
        "codebuddy": create_executor("codebuddy", config=config),
    }

def create_adapter(provider: str):
    """Create AG-UI adapter instance for provider."""
    key = normalize_provider(provider)
    
    if key == "gemini":
        from src.runtime.adapters.gemini import GeminiAGUIAdapter
        return GeminiAGUIAdapter()
    
    if key == "codex":
        from src.runtime.adapters.codex import CodexCLIAGUIAdapter
        return CodexCLIAGUIAdapter()
    
    if key == "codebuddy":
        from src.runtime.adapters.codebuddy import CodebuddyAGUIAdapter
        return CodebuddyAGUIAdapter()
    
    # Default: Claude
    from src.runtime.adapters.claude import AGUIAdapter
    return AGUIAdapter()
```

---

## 5. CONFIGURATION STRUCTURE (src/server/config.py)

**ServerSettings** (line 7-39):
- API host/port, logging, streaming settings, debug mode

**ProviderSettings** (line 169-189):
- Default provider selection
- CLI command mappings
- Provider-specific settings

**NexusSettings** (line 192-205):
- Nexus console authentication

**Settings** (line 209-215):
- Combined settings class that merges all above

```python
class ServerSettings(BaseSettings):
    # ... existing fields ...
    cli_timeout: int = 600              # Already exists
    nexus_model: str = "gpt-4o"       # Already exists
    nexus_missions_enabled: bool = True  # Already exists

class ProviderSettings(BaseSettings):
    # ... existing fields ...
    default_provider: str = "codebuddy"
    default_alias: str = ""
    default_exec_user: str = ""
```

To add nexus config:
```python
class ServerSettings(BaseSettings):
    # Add these fields:
    nexus_command: str = "nexus"
    nexus_model: str = "gpt-4o"
    nexus_workspace: str = ""
    nexus_max_iterations: int = 20
    # ... etc
```

---

## 6. CHAT ROUTER (src/server/routers/chat.py)

**How requests are dispatched:**

```python
@router.post("/chat/stream/{exec_user}", response_class=StreamingResponse)
async def chat_stream(request: Request, exec_user: str):
    """Unified chat interface (AG-UI protocol)"""
    # 1. Parse request body
    body_dict = json.loads(await request.body())
    
    # 2. Normalize provider/alias
    body_dict = _apply_query_provider_alias(request, body_dict)
    
    # 3. Create StreamHandler (uses dispatcher internally)
    stream_handler = StreamHandler()
    
    # 4. Handle AG-UI request
    return await stream_handler.handle_agui_request(request, body_dict, exec_user)
```

**StreamHandler** uses dispatcher to:
1. Create executor via `create_executor(provider)`
2. Create adapter via `create_adapter(provider)`
3. Run executor and pipe output through adapter

---

## 7. KEY FUNCTION SIGNATURES TO IMPLEMENT

### For Executor (src/providers/nexus/executor.py):

```python
class NexusExecutorConfig(ExecutorConfig):
    def __init__(
        self,
        timeout: float = 600.0,
        user_home_base: str = "/home",
        nexus_command: str = "nexus",
        **kwargs,
    ):
        super().__init__(timeout=timeout, user_home_base=user_home_base)
        self.nexus_command = nexus_command
        self.extra.update(kwargs)

class NexusExecutor(BaseExecutor):
    async def execute(
        self,
        context: RequestContext,
        output_format: str = "raw",
    ) -> AsyncGenerator[str, None]:
        """Yield JSON lines (stream-json format)"""
        # 1. Validate context
        # 2. Build command: ["nexus", "--json", context.content]
        # 3. Execute subprocess
        # 4. Read lines from stdout
        # 5. Yield JSON lines
        pass
    
    def _build_command(self, context: RequestContext) -> List[str]:
        """Return ['nexus', '--json', context.content]"""
        pass
```

### For Adapter (src/runtime/adapters/nexus/agui_adapter.py):

```python
class NexusAGUIAdapter(BaseAdapter):
    def convert(self, event: Dict[str, Any]) -> Optional[str]:
        """Transform nexus event to AG-UI format.
        
        Expected nexus event types (from docs):
        - "message_delta": Text content
        - "tool_use": Tool call
        - "tool_result": Tool result
        - "error": Error
        """
        if not self.state:
            return None
        
        event_type = event.get("type")
        
        if event_type == "message_delta":
            # Emit TextMessageStart/Content
            pass
        
        elif event_type == "tool_use":
            # Emit ToolCallStart
            pass
        
        elif event_type == "tool_result":
            # Emit ToolCallResult + ToolCallEnd
            pass
        
        elif event_type == "error":
            # Emit RunErrorEvent
            pass
        
        return None
    
    def create_start_event(self) -> Optional[str]:
        """Emit RunStartedEvent"""
        pass
    
    def create_end_event(self, is_error: bool = False, error_msg: str = "") -> str:
        """Emit RunFinishedEvent"""
        pass
    
    def create_error_event(self, error_msg: str) -> str:
        """Emit RunErrorEvent"""
        pass
```

---

## 8. REGISTRATION UPDATES NEEDED

### In src/providers/dispatcher.py:

```python
def normalize_provider(name: Optional[str]) -> str:
    n = (name or "").strip().lower()
    if n in ("gemini", "codex", "codebuddy", "nexus"):  # ADD nexus
        return n
    return "claude"

def create_executor(provider: str, *, config=None):
    # ... existing code ...
    if key == "nexus":  # ADD THIS BLOCK
        from src.providers.nexus import NexusExecutor
        return NexusExecutor(config=config)
    # ... rest of function ...

def create_all_executors(*, config=None) -> dict:
    # ... existing code ...
    return {
        "claude":    create_executor("claude", config=config),
        "gemini":    create_executor("gemini", config=config),
        "codex":     create_executor("codex", config=config),
        "codebuddy": create_executor("codebuddy", config=config),
        "nexus":   create_executor("nexus", config=config),  # ADD
    }

def create_adapter(provider: str):
    # ... existing code ...
    if key == "nexus":  # ADD THIS BLOCK
        from src.runtime.adapters.nexus import NexusAGUIAdapter
        return NexusAGUIAdapter()
    # ... rest of function ...
```

### In src/runtime/adapters/__init__.py:

```python
from .nexus import NexusAGUIAdapter  # ADD

__all__ = [
    # ... existing exports ...
    "NexusAGUIAdapter",  # ADD
]
```

### In src/server/config.py:

```python
class ServerSettings(BaseSettings):
    # Add nexus config fields:
    nexus_command: str = "nexus"
    nexus_model: str = "gpt-4o"
    nexus_workspace: str = ""
    nexus_max_iterations: int = 20
    # ... existing fields ...
```

---

## 9. EXISTING PROVIDER EXAMPLES TO REFERENCE

### Claude Provider
- **Executor**: `src/providers/claude/executor.py` (CLIExecutor)
- **Adapter**: `src/providers/claude/adapter.py` → `src/runtime/adapters/claude/agui_adapter.py`
- **Features**: Complex stream-json parsing, subagent tool call parsing, thinking tag sanitization

### Codebuddy Provider
- **Executor**: `src/providers/codebuddy/cli_executor.py` (CodebuddyCLIExecutor)
- **Adapter**: `src/runtime/adapters/codebuddy/agui_adapter.py`
- **Features**: Split thinking tag handling across stream events, text vs tool content separation

### Codex Provider
- **Executor**: `src/providers/codex/cli_executor.py` (CodexCLIExecutor)
- **Adapter**: `src/runtime/adapters/codex/cli_agui_adapter.py` (CodexCLIAGUIAdapter)
- **Features**: Codex-specific event mapping (task_started, agent_message_delta, etc.)

### Gemini Provider
- **Executor**: `src/providers/gemini/executor.py` (GeminiExecutor)
- **Adapter**: `src/runtime/adapters/gemini/agui_adapter.py` (GeminiAGUIAdapter)
- **Features**: Simpler event mapping (init, error, message, tool_use, tool_result)

---

## 10. AG-UI EVENT CLASSES (src/runtime/events/agui.py)

**Available event types to emit from adapter:**

```python
class RunStartedEvent:
    def __init__(self, threadId: str, runId: str): ...

class RunFinishedEvent:
    def __init__(self, threadId: str, runId: str): ...

class RunErrorEvent:
    def __init__(self, threadId: str, runId: str, message: str): ...

class TextMessageStartEvent:
    def __init__(self, messageId: str, role: MessageRole): ...

class TextMessageContentEvent:
    def __init__(self, messageId: str, delta: str): ...

class TextMessageEndEvent:
    def __init__(self, messageId: str): ...

class ToolCallStartEvent:
    def __init__(self, toolCallId: str, toolCallName: str, parentMessageId: str = None): ...

class ToolCallArgsEvent:
    def __init__(self, toolCallId: str, delta: str): ...

class ToolCallEndEvent:
    def __init__(self, toolCallId: str): ...

class ToolCallResultEvent:
    def __init__(self, messageId: str, toolCallId: str, content: str): ...

class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
```

Each event has a `.to_sse()` method that returns SSE-formatted string.

---

## SUMMARY: MINIMAL CHECKLIST

To add Nexus provider, you need:

1. **Create src/providers/nexus/**
   - `executor.py`: NexusExecutor(BaseExecutor)
   - `__init__.py`: Export NexusExecutor

2. **Create src/runtime/adapters/nexus/**
   - `agui_adapter.py`: NexusAGUIAdapter(BaseAdapter)
   - `__init__.py`: Export NexusAGUIAdapter

3. **Update src/providers/dispatcher.py**
   - Add "nexus" to normalize_provider() check
   - Add nexus block to create_executor()
   - Add nexus block to create_all_executors()
   - Add nexus block to create_adapter()

4. **Update src/runtime/adapters/__init__.py**
   - Import and export NexusAGUIAdapter

5. **Update src/server/config.py**
   - Add nexus_command, nexus_model, etc. to ServerSettings

6. **Optional: Update chat.py if special handling needed**
   - Usually not necessary—dispatcher handles it automatically
