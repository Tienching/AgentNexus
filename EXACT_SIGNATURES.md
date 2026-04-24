# Exact Function Signatures & Import Paths

## 1. EXECUTOR EXECUTE SIGNATURE

### Location: src/providers/base.py (Abstract)
```python
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
```

### Backward-compat signature (server layer, for migration):
```python
async def execute(
    self,
    request: Any,  # RequestModel or RequestContext
    exec_user: str = "default",
    output_format: str = "raw",
) -> AsyncGenerator[str, None]:
```

---

## 2. CLI EXECUTOR BUILD COMMAND SIGNATURE

### Location: src/providers/base.py (Abstract)
```python
@abstractmethod
def _build_command(self, context: RequestContext) -> List[str]:
    """Build the CLI command to execute.
    
    Returns:
        List of command parts to pass to subprocess
    """
    pass
```

---

## 3. BASEEXECUTOR HELPER METHODS (Use these!)

### resolve_exec_dir
```python
def resolve_exec_dir(self, context: RequestContext) -> Path:
    """Resolve the execution directory.
    
    Logic:
    - If cwd_mode="inplace" and cwd is set, use that directly
    - Otherwise, use session-based directory under user home
    """
    # Returns Path object
```

### wrap_command_for_user
```python
def wrap_command_for_user(
    self,
    cmd: List[str],
    exec_dir: Path,
    target_user: str,
) -> List[str]:
    """Wrap command with cd and optionally su.
    
    Returns:
        Shell command list ready for execution
    """
    # Handles user switching via 'su' if needed
```

### run_subprocess
```python
async def run_subprocess(
    self,
    final_cmd: List[str],
    timeout: Optional[float] = None,
) -> asyncio.subprocess.Process:
    """Create and return a subprocess.
    
    Args:
        final_cmd: Command list to execute
        timeout: Optional timeout override
        
    Returns:
        Running subprocess
    """
```

### read_stream
```python
async def read_stream(
    self,
    process: asyncio.subprocess.Process,
    timeout: float,
) -> AsyncGenerator[bytes, None]:
    """Read lines from process stdout with timeout.
    
    Args:
        process: Running subprocess
        timeout: Line read timeout
        
    Yields:
        Raw line bytes
    """
```

### drain_stderr
```python
async def drain_stderr(self, process: asyncio.subprocess.Process) -> Optional[str]:
    """Best-effort stderr drain.
    
    Returns:
        Stderr content (truncated) or None
    """
```

---

## 4. ADAPTER CONVERT SIGNATURE

### Location: src/runtime/adapters/base.py (Abstract)
```python
@abstractmethod
def convert(self, event: Dict[str, Any]) -> Optional[str]:
    """Transform provider event to AG-UI protocol format.
    
    Args:
        event: Raw event from provider (usually JSON dict)
        
    Returns:
        SSE-formatted string, or None if event doesn't apply
    """
    pass
```

---

## 5. ADAPTER START/END/ERROR SIGNATURES

### create_start_event
```python
@abstractmethod
def create_start_event(self) -> Optional[str]:
    """Create run start event.
    
    Returns:
        SSE-formatted RunStartedEvent, or None
    """
    pass
```

### create_end_event
```python
@abstractmethod
def create_end_event(self, is_error: bool = False, error_msg: str = "") -> str:
    """Create run end event.
    
    Args:
        is_error: Whether ending due to error
        error_msg: Error message if is_error=True
        
    Returns:
        SSE-formatted RunFinishedEvent (or RunErrorEvent if error)
    """
    pass
```

### create_error_event
```python
@abstractmethod
def create_error_event(self, error_msg: str) -> str:
    """Create error event.
    
    Args:
        error_msg: Error message
        
    Returns:
        SSE-formatted RunErrorEvent
    """
    pass
```

---

## 6. ADAPTER STATE MANAGEMENT

### init_state
```python
def init_state(self, thread_id: str, run_id: str) -> None:
    """Initialize adapter state for a new run.
    
    Call this before processing any events from executor.
    """
    self.state = AdapterState(thread_id, run_id)
```

### AdapterState structure
```python
class AdapterState:
    thread_id: str                                  # Session ID
    run_id: str                                     # Request ID
    current_message_id: Optional[str] = None        # Current text message
    message_started: bool = False                   # Text message in progress?
    tool_input_buffer: Dict[int, tuple] = {}       # index -> (tool_name, tool_id, params)
    active_tool_calls: Dict[str, str] = {}         # tool_id -> tool_name
    run_started: bool = False                       # RUN_STARTED sent?
    run_finished: bool = False                      # RUN_FINISHED sent?
    has_error: bool = False                         # Error flag for cleanup
```

---

## 7. AG-UI EVENT CLASSES & TO_SSE() METHOD

### All event classes have:
```python
def to_sse(self) -> str:
    """Return SSE-formatted string."""
    # Returns: "data: {...json...}\n\n"
```

### Event signatures:
```python
class RunStartedEvent:
    def __init__(self, threadId: str, runId: str): pass

class RunFinishedEvent:
    def __init__(self, threadId: str, runId: str): pass

class RunErrorEvent:
    def __init__(self, threadId: str, runId: str, message: str): pass

class TextMessageStartEvent:
    def __init__(self, messageId: str, role: MessageRole): pass

class TextMessageContentEvent:
    def __init__(self, messageId: str, delta: str): pass

class TextMessageEndEvent:
    def __init__(self, messageId: str): pass

class ToolCallStartEvent:
    def __init__(
        self,
        toolCallId: str,
        toolCallName: str,
        parentMessageId: Optional[str] = None
    ): pass

class ToolCallArgsEvent:
    def __init__(self, toolCallId: str, delta: str): pass

class ToolCallEndEvent:
    def __init__(self, toolCallId: str): pass

class ToolCallResultEvent:
    def __init__(self, messageId: str, toolCallId: str, content: str): pass
```

### MessageRole enum
```python
class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
```

---

## 8. DISPATCHER FUNCTION SIGNATURES

### normalize_provider
```python
def normalize_provider(name: Optional[str]) -> str:
    """Normalize provider name to canonical key.
    
    Unknown/empty values fall back to "claude".
    
    Returns: "claude", "gemini", "codex", "codebuddy", or "nexus"
    """
```

### create_executor
```python
def create_executor(provider: str, *, config=None):
    """Create a NEW executor instance for provider.
    
    Args:
        provider: Raw provider name (will be normalized)
        config: Optional settings object; defaults to settings
        
    Returns:
        BaseExecutor subclass instance
    """
```

### create_all_executors
```python
def create_all_executors(*, config=None) -> dict:
    """Pre-create one executor per known provider.
    
    Returns:
        Dict with keys: "claude", "gemini", "codex", "codebuddy", "nexus"
    """
```

### create_adapter
```python
def create_adapter(provider: str):
    """Create a NEW AG-UI adapter instance for provider.
    
    Args:
        provider: Raw provider name (will be normalized)
        
    Returns:
        BaseAdapter subclass instance
    """
```

---

## 9. EXACT IMPORT PATHS

### Base classes & types
```python
from src.providers.base import (
    BaseExecutor,
    ExecutorConfig,
    RequestContext,
)

from src.runtime.adapters.base import (
    BaseAdapter,
    AdapterState,
    ProtocolType,
)
```

### AG-UI events
```python
from src.runtime.events.agui import (
    RunStartedEvent,
    RunFinishedEvent,
    RunErrorEvent,
    TextMessageStartEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    ToolCallStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    MessageRole,
)
```

### Existing providers (to import from)
```python
from src.providers.claude import CLIExecutor
from src.providers.codebuddy import CodebuddyCLIExecutor
from src.providers.codex import CodexCLIExecutor
from src.providers.gemini import GeminiExecutor

from src.runtime.adapters.claude import AGUIAdapter
from src.runtime.adapters.codebuddy import CodebuddyAGUIAdapter
from src.runtime.adapters.codex import CodexCLIAGUIAdapter
from src.runtime.adapters.gemini import GeminiAGUIAdapter
```

---

## 10. CONFIG CLASSES

### RequestContext (provider receives this)
```python
@dataclass
class RequestContext:
    content: str                           # User input (required)
    user: str = "anonymous"                # API user
    session_id: str = "default"            # Session ID
    exec_user: str = "default"             # Linux user for su
    cwd: Optional[str] = None              # Working directory
    cwd_mode: str = ""                     # "inplace" or ""
    run_kind: str = ""                     # "chat_continue" etc.
    alias: Optional[str] = None            # CLI command name override
    model: Optional[str] = None            # LLM model override
    cli_session_id: Optional[str] = None   # CLI session UUID
    session_cleared: bool = False          # /clear just executed
    metadata: Dict[str, Any] = {}          # Additional metadata
    
    @classmethod
    def from_request_model(cls, model_obj: Any, exec_user: str = "default"):
        """Create from legacy RequestModel for backward compatibility."""
```

### ExecutorConfig (provider receives this)
```python
@dataclass
class ExecutorConfig:
    timeout: float = 600.0                 # Subprocess timeout
    user_home_base: str = "/home"          # Base directory for user home
    extra: Dict[str, Any] = {}             # Provider-specific extras
```

### ServerSettings (from src/server/config.py)
```python
class ServerSettings(BaseSettings):
    # Existing fields:
    api_host: str = "0.0.0.0"
    api_port: int = 8081
    cli_timeout: int = 600                 # CLI timeout in seconds
    nexus_model: str = "gpt-4o"          # Already exists
    nexus_missions_enabled: bool = True  # Already exists
    # Add these for nexus:
    nexus_command: str = "nexus"       # CLI command to invoke
    nexus_workspace: str = ""            # Default workspace
    nexus_max_iterations: int = 20       # Max iterations
```

---

## 11. STREAM FORMAT EXPECTATIONS

### Provider yields JSON lines:
Each line from executor's `execute()` should be a JSON string:
```json
{"type": "message_delta", "content": "Hello"}
{"type": "tool_use", "tool_id": "123", "tool_name": "search"}
{"type": "tool_result", "tool_id": "123", "result": "..."}
{"type": "error", "message": "Something failed"}
```

### Adapter converts to AG-UI SSE format:
Each line from adapter should be SSE format:
```
data: {"type":"TEXT_MESSAGE_START","messageId":"msg-001","role":"assistant"}

data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"msg-001","delta":"Hello"}

data: {"type":"TEXT_MESSAGE_END","messageId":"msg-001"}

data: {"type":"RUN_FINISHED","runId":"run-123"}

```

---

## 12. CRITICAL: DO NOT BREAK EXISTING PATTERNS

### ✅ Must follow pattern:
- Provider executor must yield **JSON lines** (one per line)
- Adapter's `convert()` receives one event dict at a time
- Both must use `.to_sse()` method on event objects
- Both must handle `None` gracefully (skip if not applicable)

### ❌ Do NOT:
- Modify BaseExecutor or BaseAdapter signatures
- Break the RequestContext contract
- Mix formatting logic (event conversion stays in adapter)
- Yield multiple events per line from executor
- Assume order of events

---

## 13. TESTING: MINIMAL TEST STRUCTURE

### Test executor:
```python
async def test_nexus_executor():
    config = NexusExecutorConfig()
    executor = NexusExecutor(config)
    
    context = RequestContext(
        content="test prompt",
        user="testuser",
        session_id="test-session"
    )
    
    lines = []
    async for line in executor.execute(context):
        lines.append(line)
    
    # Verify each line is valid JSON
    for line in lines:
        event = json.loads(line)
        assert isinstance(event, dict)
        assert "type" in event
```

### Test adapter:
```python
async def test_nexus_adapter():
    adapter = NexusAGUIAdapter()
    adapter.init_state("thread-123", "run-456")
    
    # Test event conversion
    event = {"type": "message_delta", "content": "Hello"}
    result = adapter.convert(event)
    
    # Should return SSE format string
    assert result is not None
    assert "data:" in result
    assert json.loads(result.split("data: ")[1]) # Valid JSON
```

