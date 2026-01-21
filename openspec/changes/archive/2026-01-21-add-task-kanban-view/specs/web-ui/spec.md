## ADDED Requirements

### Requirement: REQ-UI-008 View Switcher (Chat/Task)
系统 MUST 在 `/nexus/` 页面提供视图切换入口，至少包含 `Chat` 与 `Task` 两个视图。

#### Scenario: Switch between Chat and Task
- **Given** 用户访问 `/nexus/`
- **When** 用户点击 `Task` 视图入口
- **Then** 页面切换为任务看板视图
- **And** 用户再次点击 `Chat` 视图入口时，页面切回会话浏览视图

### Requirement: REQ-UI-009 Task Kanban Board
系统 MUST 提供任务看板视图，用于展示通过 `/think` 或 `/task` 创建的任务。

#### Scenario: Display tasks grouped by status columns
- **Given** 系统中存在多个不同状态的任务
- **When** 用户打开 `Task` 视图
- **Then** 任务按状态分列展示（To Do / Doing / Done / Failed / Cancelled）
- **And** 每个任务卡片至少展示任务 id 与描述

#### Scenario: Display task workspace
- **Given** 某任务在创建时包含 `workspace`
- **When** 用户在 `Task` 视图查看该任务卡片
- **Then** 卡片展示该任务的 `workspace`

### Requirement: REQ-UI-010 Task Detail and AGUI Log Viewer
系统 MUST 允许用户查看任务详情，并展示该任务的对话记录（以 AGUI 方式展示）。

#### Scenario: Open task detail
- **Given** 用户在 `Task` 视图
- **When** 用户点击某个任务卡片
- **Then** 页面展示任务详情（至少包含状态、描述、workspace、时间字段）

#### Scenario: Display task conversation via AGUI messages
- **Given** 某任务存在可读取的对话记录
- **When** 用户打开该任务详情
- **Then** 系统通过 AGUI messages（例如 `MESSAGES_SNAPSHOT`）展示任务对话内容

## Related Capabilities
- `web-api`: 依赖此能力获取任务列表/详情/日志
