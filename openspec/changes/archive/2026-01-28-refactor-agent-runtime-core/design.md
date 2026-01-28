## Context

当前系统存在三条独立变化轴：
- **Provider**：模型后端（claude/gemini/codex）
- **Protocol**：对外协议（AGUI/企微协议）
- **Channel**：消息通道（企微/Slack/Telegram）

这三者目前耦合严重，导致：
1. 协议适配器依赖 provider raw event 格式
2. gemini_cli_api 反向依赖 claude_code_api
3. 无法灵活添加新 channel

## Goals / Non-Goals

### Goals
- 建立统一的 `agent_runtime` 核心包
- 三层解耦：Provider → Events → Protocol/Channel
- 支持 CLI 快速安装/配置
- 现有功能不受影响

### Non-Goals
- 实现所有 channel（本次只做 WeWork）
- 实现 codex provider（留给后续）
- WebSocket 实时推送
- 多租户/权限体系

## Decisions

### 1. 包结构
```
src/agent_runtime/
├── events/           # 统一事件模型
│   ├── __init__.py
│   ├── base.py       # Event 基类
│   └── types.py      # 具体事件类型
├── runtime/          # 执行核心
│   ├── __init__.py
│   ├── session.py    # 会话管理
│   ├── task.py       # 任务管理
│   └── archiver.py   # 归档
├── providers/        # Provider 插件
│   ├── __init__.py
│   ├── base.py       # Provider Protocol
│   ├── registry.py   # 注册表
│   ├── claude/       # Claude Provider
│   └── gemini/       # Gemini Provider
├── protocols/        # 输出协议
│   ├── __init__.py
│   ├── base.py       # Protocol 接口
│   ├── agui.py       # AGUI 协议
│   └── wecom.py      # 企微协议（原 legacy）
├── channels/         # 消息通道
│   ├── __init__.py
│   ├── base.py       # Channel 接口
│   ├── registry.py   # Channel 注册
│   └── wecom/        # 企微 Channel
├── routing/          # 路由规则
│   ├── __init__.py
│   └── session_key.py
└── plugins/          # CLI 与安装器
    ├── __init__.py
    ├── cli.py        # vhsdk 入口
    └── installer.py  # 安装逻辑
```

**理由**：按职责单一原则拆分，每层只依赖下层或 events 层。

### 2. 统一事件模型

```python
# events/types.py
from dataclasses import dataclass
from typing import Any, Optional
from enum import Enum

class EventType(Enum):
    TOKEN = "token"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_END = "tool_call_end"
    TOOL_RESULT = "tool_result"
    MESSAGE_START = "message_start"
    MESSAGE_END = "message_end"
    ERROR = "error"
    SYSTEM = "system"

@dataclass
class Event:
    type: EventType
    data: dict[str, Any]
    timestamp: float
    provider: str
    session_id: Optional[str] = None

@dataclass
class TokenEvent(Event):
    text: str

@dataclass
class ToolCallEvent(Event):
    tool_name: str
    tool_id: str
    arguments: dict[str, Any]
    
@dataclass  
class ErrorEvent(Event):
    code: str
    message: str
    recoverable: bool = True
```

**理由**：统一事件模型让 Protocol/Channel 不再关心 provider 实现细节。

### 3. Provider 接口

```python
# providers/base.py
from typing import Protocol, AsyncIterator
from ..events.types import Event

class Provider(Protocol):
    name: str
    
    async def execute(
        self,
        prompt: str,
        context: "RunContext",
    ) -> AsyncIterator[Event]:
        """执行并产出统一事件流"""
        ...
    
    def supports_capability(self, cap: str) -> bool:
        """检查是否支持某能力"""
        ...
```

**理由**：Provider 只负责"执行 + 翻译成 events"，不关心输出目的地。

### 4. Channel 接口

```python
# channels/base.py
from typing import Protocol, AsyncIterator
from ..events.types import Event

class Channel(Protocol):
    name: str
    
    async def receive(self) -> AsyncIterator["InboundMessage"]:
        """接收消息"""
        ...
    
    async def send(self, message: "OutboundMessage") -> None:
        """发送消息"""
        ...
    
    def get_session_key(self, msg: "InboundMessage") -> str:
        """生成 session key（参考 Clawdbot）"""
        ...

@dataclass
class InboundMessage:
    channel: str
    peer_id: str
    group_id: Optional[str]
    thread_id: Optional[str]
    content: str
    attachments: list[Any]

@dataclass
class OutboundMessage:
    channel: str
    peer_id: str
    group_id: Optional[str]
    thread_id: Optional[str]
    content: str
    format: str  # "text" | "markdown" | "rich"
```

**理由**：基于 Clawdbot 的设计，session_key 由 channel 决定，确定性路由。

### 5. CLI 设计

```bash
# 安装 channel
vhsdk install channel wecom
vhsdk install channel slack

# 安装 provider
vhsdk install provider codex

# 列出已安装
vhsdk list

# 生成配置
vhsdk config init
```

**实现**：通过 `pyproject.toml` 的 `[project.optional-dependencies]` + `pip install vhsdk[wecom]` 或独立安装脚本。

### 6. 依赖方向

```
claude_code_api ──┐
gemini_cli_api ───┼──▶ agent_runtime
codex_code_api ───┘         │
                            ▼
                    ┌───────┴───────┐
                    │    events     │
                    └───────┬───────┘
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
          providers     protocols     channels
```

**规则**：
- API surfaces 依赖 agent_runtime
- agent_runtime 内部：providers/protocols/channels 依赖 events
- 无循环依赖

## Risks / Trade-offs

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 重构范围大 | 高 | 分 Phase 执行，每阶段测试 |
| 事件模型不够灵活 | 中 | 预留 `data: dict` 扩展字段 |
| CLI 依赖管理复杂 | 中 | 使用 extras 或 uv 管理 |
| Channel 插件加载性能 | 低 | 延迟加载，按需导入 |

## Migration Plan

### 兼容性保证
1. 保留 `claude_code_api/adapters/` 作为兼容层，代理到新 protocols
2. 保留 `providers/registry.py` 作为旧入口，内部转发到 agent_runtime
3. 旧 API 路由不变，内部实现迁移

### 回滚方案
1. 每个 Phase 可独立回滚
2. 保留旧代码路径，通过 feature flag 切换
3. 测试覆盖关键路径

## Open Questions

1. ~~CLI 命令名~~ → 确定为 `vhsdk`
2. ~~legacy 定位~~ → 确定为企微协议（wecom protocol）
3. channel 配置存储位置？建议 `~/.config/vhsdk/channels/` 或项目 `config/channels/`
4. 是否需要 channel 热插拔？建议本次不做，重启生效即可
