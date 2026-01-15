# session-storage Specification

## Purpose
TBD - created by archiving change add-nexushub-web-viewer. Update Purpose after archive.
## Requirements
### Requirement: REQ-SS-001 Session Metadata Storage
系统必须能够存储和检索会话元信息。

#### Scenario: Save new session metadata
- **Given** 一个新的 AGUI 会话开始
- **When** 调用 `save_session_meta(meta)` 
- **Then** 会话元信息保存到 Redis Hash `aona:session:{id}:meta`
- **And** 会话 ID 添加到用户索引 `aona:user:{username}:sessions`

#### Scenario: Retrieve session metadata
- **Given** 会话 ID 存在于 Redis
- **When** 调用 `get_session_meta(session_id)`
- **Then** 返回完整的 `SessionMeta` 对象

#### Scenario: Session not found
- **Given** 会话 ID 不存在
- **When** 调用 `get_session_meta(session_id)`
- **Then** 返回 `None`

### Requirement: REQ-SS-002 User Sessions Index
系统必须维护用户的会话索引，支持按时间排序。

#### Scenario: List user sessions
- **Given** 用户有多个会话
- **When** 调用 `get_user_sessions(username)`
- **Then** 返回按 `updated_at` 降序排列的会话列表

#### Scenario: User has no sessions
- **Given** 用户没有任何会话
- **When** 调用 `get_user_sessions(username)`
- **Then** 返回空列表

### Requirement: REQ-SS-003 Message Storage
系统必须能够存储和检索会话消息。

#### Scenario: Add message to session
- **Given** 一个存在的会话
- **When** 调用 `add_session_message(session_id, message)`
- **Then** 消息追加到 Redis List `aona:session:{id}:messages`
- **And** 会话的 `message_count` 增加
- **And** 会话的 `updated_at` 更新

#### Scenario: Get session messages
- **Given** 会话有多条消息
- **When** 调用 `get_session_messages(session_id)`
- **Then** 返回按时间顺序排列的消息列表

### Requirement: REQ-SS-004 Tool Call Storage
系统必须能够存储和检索工具调用记录。

#### Scenario: Save tool call
- **Given** 一个 AGUI 工具调用事件
- **When** 调用 `save_tool_call(session_id, tool_call)`
- **Then** 工具调用保存到 Redis Hash `aona:session:{id}:toolcalls`

#### Scenario: Get tool call by ID
- **Given** 工具调用 ID 存在
- **When** 调用 `get_tool_call(session_id, tool_call_id)`
- **Then** 返回完整的 `StoredToolCall` 对象

#### Scenario: Get all session tool calls
- **Given** 会话有多个工具调用
- **When** 调用 `get_session_tool_calls(session_id)`
- **Then** 返回所有工具调用的列表

### Requirement: REQ-SS-005 Session Status Management
系统必须能够更新和查询会话状态。

#### Scenario: Update session status
- **Given** 一个存在的会话
- **When** 调用 `update_session_status(session_id, "running")`
- **Then** 会话状态更新为 "running"
- **And** `updated_at` 时间戳更新

### Requirement: REQ-SS-006 Session Deletion
系统必须能够删除会话及其所有关联数据。

#### Scenario: Delete session
- **Given** 一个存在的会话
- **When** 调用 `delete_session(session_id, username)`
- **Then** 删除 `aona:session:{id}:meta`
- **And** 删除 `aona:session:{id}:messages`
- **And** 删除 `aona:session:{id}:toolcalls`
- **And** 从 `aona:user:{username}:sessions` 移除

### Requirement: REQ-SS-007 Data Expiration
会话数据必须有 TTL 以避免无限增长。

#### Scenario: Session data expires
- **Given** 会话数据保存 7 天后
- **When** TTL 到期
- **Then** Redis 自动删除会话相关的所有 key

