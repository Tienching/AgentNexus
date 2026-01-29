## ADDED Requirements

### Requirement: REQ-API-010 Create Task with Dependencies
创建任务 API MUST 支持指定任务依赖关系。

#### Scenario: Create task with depends_on parameter
- **Given** 用户调用 `POST /api/nexus/tasks`
- **When** 请求体包含 `depends_on: ["task-001", "task-002"]`
- **Then** 任务被创建
- **And** 返回的任务数据包含 `depends_on` 字段

#### Scenario: Create task with invalid dependency
- **Given** 用户调用 `POST /api/nexus/tasks`
- **When** 请求体包含不存在的任务 ID（`depends_on: ["non-existent"]`）
- **Then** 任务仍然被创建（不做前置校验）
- **And** 该任务将永远阻塞直到手动解除

### Requirement: REQ-API-011 Update Task Status
系统 MUST 提供手动更新任务状态的 API。

#### Scenario: Update task status to done
- **Given** 任务 ID 存在且状态为 `failed`
- **When** 请求 `PATCH /api/nexus/tasks/{task_id}/status` 并指定 `status: "done"`
- **Then** 任务状态更新为 `done`
- **And** 返回更新后的任务数据

#### Scenario: Update task status to cancel blocked task
- **Given** 任务 B 依赖任务 A，任务 A 状态为 `failed`
- **When** 请求 `PATCH /api/nexus/tasks/{task_id}/status` 对任务 B 设置 `status: "cancelled"`
- **Then** 任务 B 状态更新为 `cancelled`
- **And** 任务 B 不再参与调度

### Requirement: REQ-API-012 Get Task with Dependency Info
获取任务详情 API MUST 返回依赖关系信息。

#### Scenario: Get task with dependencies
- **Given** 任务 B 依赖任务 A
- **When** 请求 `GET /api/nexus/tasks/{task_id}`
- **Then** 返回的任务数据包含 `depends_on: ["task-A"]`

#### Scenario: Get task dependency status
- **Given** 任务 B 依赖任务 A 和任务 C
- **When** 请求 `GET /api/nexus/tasks/{task_id}`
- **Then** 返回的任务数据包含 `depends_on` 字段
- **And** 编排器可以查询依赖任务的状态来判断是否可执行
