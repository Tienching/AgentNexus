## ADDED Requirements

### Requirement: REQ-API-007 List Tasks
系统 MUST 提供获取任务列表的 API。

#### Scenario: List tasks by agent
- **Given** 某 `exec_user` 下存在多个任务
- **When** 请求 `GET /api/nexus/tasks?exec_user=ubuntu`
- **Then** 返回该 agent 的任务列表

#### Scenario: Filter tasks by status
- **Given** 任务存在不同状态
- **When** 请求 `GET /api/nexus/tasks?status=todo`
- **Then** 只返回状态为 `todo` 的任务

### Requirement: REQ-API-008 Get Task Detail
系统 MUST 提供获取单个任务详情的 API。

#### Scenario: Get existing task
- **Given** 任务 ID 存在
- **When** 请求 `GET /api/nexus/tasks/{task_id}`
- **Then** 返回该任务详情（包含 `status`、`priority`、`workspace` 等字段）

#### Scenario: Task not found
- **Given** 任务 ID 不存在
- **When** 请求 `GET /api/nexus/tasks/{task_id}`
- **Then** 返回 404 错误

### Requirement: REQ-API-009 Get Task Conversation (AGUI)
系统 MUST 提供获取任务对话记录的 API，并以 AG-UI/AGUI 的事件或消息模型返回。

#### Scenario: Return messages snapshot
- **Given** 任务的 `conversation.json` 可读取
- **When** 请求 `GET /api/nexus/tasks/{task_id}/agui/messages`
- **Then** 返回一个 AGUI `MESSAGES_SNAPSHOT` 事件或等价结构

#### Scenario: Missing conversation log
- **Given** 任务尚未执行或日志不存在
- **When** 请求 `GET /api/nexus/tasks/{task_id}/agui/messages`
- **Then** 返回 404 或返回空消息列表（实现可择一，但必须明确且稳定）

## Related Capabilities
- `web-ui`: 此能力为 Web UI 提供任务数据接口
- `task-storage`: 间接依赖（通过服务层访问 Redis）
