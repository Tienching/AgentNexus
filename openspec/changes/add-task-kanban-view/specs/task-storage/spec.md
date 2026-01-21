## ADDED Requirements

### Requirement: REQ-TS-001 Task Storage Key Patterns
系统 MUST 能够在 Redis 中存储任务数据，并按 `agent_name` 进行隔离。

#### Scenario: Store task in Redis
- **Given** 用户通过 `/think` 或 `/task` 创建了一个任务
- **When** 系统写入任务数据
- **Then** 任务保存到 `aona:task:{agent}:{task_id}`（或等价的 prefix+key 结构）
- **And** 任务 ID 进入 `aona:tasks:{agent}:all` 以支持按时间排序

### Requirement: REQ-TS-002 Task Indexes for Query
系统 MUST 维护任务的索引以支持按状态、项目、workspace 查询。

#### Scenario: Index by status and workspace
- **Given** 任务创建时包含 `status` 与 `workspace`
- **When** 系统保存任务
- **Then** 任务 ID 被加入 `aona:tasks:{agent}:by_status:{status}`
- **And** 任务 ID 被加入 `aona:tasks:{agent}:by_workspace:{workspace_hash}`

### Requirement: REQ-TS-003 Task Status Transitions
系统 MUST 能够将任务从 `todo` 更新为 `doing`，并在完成后更新为 `done` 或 `failed`。

#### Scenario: Start and complete task
- **Given** 某任务状态为 `todo`
- **When** 执行器开始执行该任务
- **Then** 任务状态更新为 `doing` 并记录 `started_at`
- **When** 任务执行结束且无错误
- **Then** 任务状态更新为 `done` 并记录 `completed_at`
