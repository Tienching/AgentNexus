# web-api Specification

## Purpose
Defines the NexusHub Web API for session and task management.
## Requirements
### Requirement: REQ-API-001 List Sessions
系统 MUST 提供获取用户会话列表的 API。

#### Scenario: Get sessions with pagination
- **Given** 用户有 50 个会话
- **When** 请求 `GET /api/nexus/sessions?username=testuser&page=1&page_size=20`
- **Then** 返回前 20 个会话
- **And** 响应包含 `total`, `page`, `page_size`, `sessions` 字段

#### Scenario: Search sessions by title
- **Given** 用户有会话标题包含 "测试"
- **When** 请求 `GET /api/nexus/sessions?username=testuser&search=测试`
- **Then** 返回标题匹配的会话

#### Scenario: Filter sessions by status
- **Given** 用户有不同状态的会话
- **When** 请求 `GET /api/nexus/sessions?username=testuser&status=running`
- **Then** 只返回状态为 "running" 的会话

#### Scenario: Get all sessions without username
- **Given** 请求未提供 username
- **When** 请求 `GET /api/nexus/sessions`
- **Then** 返回所有用户的会话

### Requirement: REQ-API-002 Get Session Detail
系统 MUST 提供获取单个会话详情的 API。

#### Scenario: Get existing session
- **Given** 会话 ID 存在
- **When** 请求 `GET /api/nexus/sessions/{id}`
- **Then** 返回完整的会话元信息

#### Scenario: Session not found
- **Given** 会话 ID 不存在
- **When** 请求 `GET /api/nexus/sessions/{id}`
- **Then** 返回 404 错误

### Requirement: REQ-API-003 Get Session Messages
系统 MUST 提供获取会话消息的 API。

#### Scenario: Get messages with tool calls
- **Given** 会话有消息和工具调用
- **When** 请求 `GET /api/nexus/sessions/{id}/messages`
- **Then** 返回 `messages` 和 `tool_calls` 列表

#### Scenario: Session has no messages
- **Given** 会话没有消息
- **When** 请求 `GET /api/nexus/sessions/{id}/messages`
- **Then** 返回空的 `messages` 列表

### Requirement: REQ-API-004 Delete Session
系统 MUST 提供删除会话的 API。

#### Scenario: Delete existing session
- **Given** 会话 ID 存在
- **When** 请求 `DELETE /api/nexus/sessions/{id}?username=testuser`
- **Then** 返回 200 成功
- **And** 会话数据从 Redis 删除

#### Scenario: Delete non-existent session
- **Given** 会话 ID 不存在
- **When** 请求 `DELETE /api/nexus/sessions/{id}?username=testuser`
- **Then** 返回 200 成功（幂等操作）

### Requirement: REQ-API-005 Cancel Running Session
系统 MUST 提供取消运行中会话的 API。

#### Scenario: Cancel running session
- **Given** 会话状态为 "running"
- **When** 请求 `POST /api/nexus/sessions/{id}/cancel`
- **Then** 会话状态更新为 "completed"
- **And** 返回 `{"success": true, "cancelled": true}`

#### Scenario: Cancel non-running session
- **Given** 会话状态为 "completed"
- **When** 请求 `POST /api/nexus/sessions/{id}/cancel`
- **Then** 返回 `{"success": true, "cancelled": false}`

### Requirement: REQ-API-006 API Response Format
所有 API MUST 返回统一的 JSON 格式。

#### Scenario: Successful response
- **Given** API 调用成功
- **When** 返回响应
- **Then** Content-Type 为 `application/json`
- **And** 响应体为有效 JSON

#### Scenario: Error response
- **Given** API 调用失败
- **When** 返回错误响应
- **Then** 包含 `error` 字段说明错误原因
- **And** HTTP 状态码反映错误类型

### Requirement: REQ-API-008 Flattened Runtime Layout
运行时与 provider 目录结构 MUST 扁平化到 `src/` 下，并保证 Web API 行为与现有规范一致。

#### Scenario: Provider packages reside under src/providers
- **WHEN** 运行时加载 provider
- **THEN** provider 包路径 MUST 位于 `src/providers/`

### Requirement: REQ-API-009 Provider/Channel Placement
Provider 与 Channel 实现 MUST 位于 `src/providers` 下，`src/runtime` 只保留核心框架模块。

#### Scenario: Provider and Channel imports
- **WHEN** 运行时加载 provider 或 channel
- **THEN** 其代码路径 MUST 位于 `src/providers/`

