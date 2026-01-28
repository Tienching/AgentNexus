# channels Specification

## Purpose
TBD - created by archiving change refactor-agent-runtime-core. Update Purpose after archive.
## Requirements
### Requirement: Channel Plugin Interface
系统 SHALL 定义 Channel 插件接口：
- `receive() -> AsyncIterator[InboundMessage]`：接收消息
- `send(message: OutboundMessage) -> None`：发送消息
- `get_session_key(msg) -> str`：生成 session key

#### Scenario: Channel receives message
- **WHEN** Channel 收到外部消息（webhook/轮询）
- **THEN** 转换为 `InboundMessage` 并通过 `receive()` 产出

#### Scenario: Channel sends message
- **WHEN** 调用 `channel.send(outbound)`
- **THEN** 将消息发送到对应平台

### Requirement: WeWork Channel
系统 SHALL 提供企业微信 Channel 实现：
- 支持接收企微应用消息
- 支持发送文本/Markdown 消息
- 支持 session_key 生成（基于 user_id + corp_id）

#### Scenario: Receive WeWork message
- **WHEN** 企微 webhook 推送消息
- **THEN** 解析为 InboundMessage，包含 peer_id/group_id/content

#### Scenario: Send WeWork message
- **WHEN** 调用 wecom.send() 发送消息
- **THEN** 通过企微 API 发送到用户/群

### Requirement: Channel Registry
系统 SHALL 提供 Channel 注册表：
- 按名称注册/获取 Channel
- 支持多 Channel 同时运行
- 配置驱动的 Channel 启用

#### Scenario: Get channel by name
- **WHEN** 调用 `channel_registry.get("wecom")`
- **THEN** 返回 WeWork Channel 实例

#### Scenario: List enabled channels
- **WHEN** 调用 `channel_registry.list_enabled()`
- **THEN** 返回配置中启用的 Channel 列表

### Requirement: Channel Routing
系统 SHALL 支持 Channel 路由：
- 根据 InboundMessage 生成 session_key
- 将消息路由到对应 session/agent
- 支持 Clawdbot 风格的确定性路由

#### Scenario: Route to session
- **WHEN** Channel 收到消息
- **THEN** 根据 session_key 路由到已有或新建 session

#### Scenario: Deterministic session key
- **WHEN** 同一用户在同一 channel 发送多条消息
- **THEN** 生成相同的 session_key

