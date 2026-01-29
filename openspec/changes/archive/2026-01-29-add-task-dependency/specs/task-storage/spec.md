## ADDED Requirements

### Requirement: REQ-TS-004 Task Dependency Declaration
任务 MUST 能够声明对其他任务的依赖关系。

#### Scenario: Create task with dependencies
- **Given** 已存在任务 task-001、task-002、task-003
- **When** 创建新任务并指定 `depends_on: ["task-001", "task-002", "task-003"]`
- **Then** 新任务保存时包含 `depends_on` 字段
- **And** 依赖的 task_id 列表被持久化到 Redis

#### Scenario: Create task without dependencies
- **Given** 用户创建任务时不指定 `depends_on`
- **When** 系统保存任务
- **Then** `depends_on` 字段为空列表

### Requirement: REQ-TS-005 Dependency-Aware Task Scheduling
调度器 MUST 在所有依赖任务完成后才执行被依赖的任务。

#### Scenario: Block task until dependencies complete
- **Given** 任务 B 依赖任务 A（`depends_on: ["task-A"]`）
- **And** 任务 A 状态为 `doing`
- **When** 调度器尝试获取下一个可执行任务
- **Then** 任务 B 不会被返回执行

#### Scenario: Execute task after all dependencies complete
- **Given** 任务 C 依赖任务 A 和任务 B
- **And** 任务 A 状态为 `done`，任务 B 状态为 `done`
- **When** 调度器尝试获取下一个可执行任务
- **Then** 任务 C 可以被返回执行

#### Scenario: Keep task blocked when dependency fails
- **Given** 任务 B 依赖任务 A
- **And** 任务 A 状态变为 `failed`
- **When** 调度器尝试获取下一个可执行任务
- **Then** 任务 B 保持阻塞状态（不自动失败）
- **And** 用户可以手动修改任务 A 状态或任务 B 的依赖关系来解除阻塞
