# agent-runtime Specification

## Purpose
TBD - created by archiving change refactor-agent-runtime-core. Update Purpose after archive.
## Requirements
### Requirement: Unified Event Model
系统 SHALL 定义统一的内部事件模型，包括：
- `TokenEvent`：文本 token
- `ToolCallEvent`：工具调用开始/结束
- `ToolResultEvent`：工具执行结果
- `MessageStartEvent` / `MessageEndEvent`：消息边界
- `ErrorEvent`：错误事件
- `SystemEvent`：系统事件

所有 Provider 输出 SHALL 转换为统一事件流。

#### Scenario: Provider outputs unified events
- **WHEN** Provider 执行用户请求
- **THEN** 输出统一的 Event 流，而非 raw provider 格式

#### Scenario: Protocol consumes events
- **WHEN** Protocol adapter 接收事件流
- **THEN** 可处理任意 Provider 产出的事件，无需感知具体 Provider

### Requirement: Provider Registry
系统 SHALL 提供 Provider 注册表，支持：
- 注册/获取 Provider 实现
- 按名称解析 Provider（claude/gemini/codex）
- 默认 Provider 配置

#### Scenario: Get provider by name
- **WHEN** 调用 `registry.get("gemini")`
- **THEN** 返回 Gemini Provider 实例

#### Scenario: Default provider fallback
- **WHEN** 未指定 provider
- **THEN** 使用配置的默认 provider（默认 claude）

### Requirement: Provider Interface
Provider SHALL 实现统一接口：
- `execute(prompt, context) -> AsyncIterator[Event]`
- `supports_capability(cap) -> bool`
- `name: str` 属性

#### Scenario: Execute returns event stream
- **WHEN** 调用 `provider.execute(prompt, ctx)`
- **THEN** 返回异步迭代器产出 Event 对象

### Requirement: Protocol Layer
系统 SHALL 支持多种输出协议：
- AGUI 协议（Nexus UI）
- 企微协议（原 legacy）

Protocol adapter SHALL 只依赖统一事件模型。

#### Scenario: AGUI protocol output
- **WHEN** 使用 AGUI 协议输出
- **THEN** 将 Event 流转换为 AGUI SSE 格式

#### Scenario: WeWork protocol output
- **WHEN** 使用企微协议输出
- **THEN** 将 Event 流转换为企微兼容格式

### Requirement: Runtime Core Independence
`agent_runtime` 包 SHALL 不依赖：
- FastAPI 或任何 Web 框架
- 具体 API surface（claude_code_api 等）

API surfaces SHALL 依赖 `agent_runtime`，反向不成立。

#### Scenario: Import without web framework
- **WHEN** 在无 FastAPI 环境 import agent_runtime
- **THEN** 可正常使用 events/providers/protocols

