# Design: Task Kanban View + AGUI Task Log Replay

## Context
当前系统包含两套相关但未打通的能力：
- `NexusHub` 风格的 Web UI（`/nexus/`）用于浏览已归档的 AGUI 会话（`/api/nexus/sessions*`）。
- `/think` 任务模式：通过 `SlashCommandHandler` 创建任务，任务写入 Redis（`TaskQueue`），并由 `TaskExecutor` 后台执行；任务执行产生的对话记录主要落盘在 `/home/<agent>/sessions/task_<task_id>/.claude/conversation.json`。

问题在于：任务与其对话记录没有被 Web UI 展示出来，导致“任务模式不可见”。

## Goals / Non-Goals
- **Goals**
  - 在现有 `/nexus/` 页面中提供 `Chat` 与 `Task` 两个视图。
  - `Task` 视图以 Kanban 看板展示任务（按状态列）。
  - 支持查看任务详情（含 workspace、状态、时间、错误信息）。
  - 支持查看任务执行对话记录，并通过 AG-UI/AGUI 的事件/消息模型展示。
  - `/task` 作为主命令，`/think` 作为别名兼容。

- **Non-Goals**
  - 不在首版实现拖拽改状态、任务编辑、权限系统。
  - 不强制把任务执行过程实时推送到前端（首版以回放/快照为主）。

## Decisions

### 1) UI 信息架构：在 `/nexus/` 单页应用中引入双视图（Chat/Task）
- `Chat`：复用当前会话列表 + 详情（历史记录浏览）。
- `Task`：新增 Kanban Board（列：To Do / Doing / Done / Failed / Cancelled）。
- 两个视图共享同一静态页面与基础样式，避免引入新的构建体系。

### 2) Task API：在 `/api/nexus/` 下新增任务相关端点
- 路由保持同一命名空间，降低前端集成成本。
- 任务按 `agent_name` 隔离（与 `TaskQueue(agent_name=...)` 一致），API 默认使用配置/环境中的默认 agent（当前为 `ubuntu`）。

### 3) Task 对话记录：从 `conversation.json` 生成 AGUI 事件
- 由于任务执行不走 `StreamHandler`，其对话记录不一定被写入现有 `session-storage`。
- 首版采用“读取并转换”策略：
  - 读取 `/home/<agent>/sessions/task_<task_id>/.claude/conversation.json`
  - 转换为 **至少一个** `MESSAGES_SNAPSHOT` 事件（AGUI），其中消息内容做最小清洗：
    - 将 `content` 为 list 的结构尽量拼成可读文本（与现有 `/log` 的解析一致）
    - 对 `<think>` 等标签沿用现有清理策略
- 输出形式：
  - `GET /api/nexus/tasks/{id}/agui/messages` 返回一个 `MessagesSnapshotEvent` 的 JSON（或事件数组）；
  - 可选扩展：`text/event-stream` 的 replay（逐条发送），以支持更接近“回放”的体验。

### 4) Slash command 命名升级：`/task` 主命令 + `/think` 兼容
- 保留历史脚本/用户习惯：`/think` 仍创建任务。
- 文档与帮助输出中以 `/task` 为主（引导迁移）。

## Risks / Trade-offs
- **读取 `/home` 下日志的权限/路径差异**：不同部署下 `user_home_base` 可能变化。
  - Mitigation：基于 `settings.user_home_base` + `agent_name` + `task_id` 拼路径；不存在则返回“暂无日志”。
- **日志体积大**：conversation 可能很长。
  - Mitigation：API 支持 `limit`/`tail` 参数（例如仅返回最近 N 条消息）。
- **AGUI 语义不完整**：conversation.json 不一定包含精确的 tool-call 时间线。
  - Mitigation：首版以消息快照为主；后续如需要完全 fidelity，可在任务执行阶段接入 `StreamArchiver`。

## Migration Plan
- 兼容期内同时支持 `/think` 与 `/task`。
- UI 默认落在 `Chat` 视图，`Task` 视图作为新增入口。

## Open Questions
- 是否需要在 Kanban 上支持拖拽变更状态（并写回 Redis）？
- Task 视图是否需要按 `project`/`workspace` 的筛选器（类似现有 `usernameFilter`）？
- 任务对话展示是否必须“逐事件回放”（SSE），还是 `MESSAGES_SNAPSHOT` 快照即可？
