# Proposal: Add Task Kanban View for /think (aka /task)

## Change ID
`add-task-kanban-view`

## Summary
在现有 `/nexus/` 页面基础上新增一个 `Task` 视图（看板/Kanban），用于展示由 `/think`（改名为 `/task`，并保留 `/think` 兼容）创建的任务；并支持查看每个任务的 `workspace` 与该任务执行产生的对话记录（以 AG-UI/AGUI 事件形式回放/展示）。现有 NexusHub 会话浏览视图保留并在 UI 中标记为 `Chat` 视图（用于历史会话）。

## Why
- 当前系统已经支持 `/think` 任务模式（任务入队、状态流转、执行器），但缺少可视化入口，用户无法在 Web 端查看任务列表与执行记录。
- 任务执行会产生 `.claude/conversation.json`，但不在现有 `/nexus/` 会话列表中可见。
- 参考 NexusHub 的 Kanban 交互模式，提供更直观的任务队列视图与可追溯的执行对话。

## What Changes
1. **Web UI**：在 `/nexus/` 单页应用中新增顶部视图切换（`Chat` / `Task`）。
2. **Task 看板**：`Task` 视图按任务状态（To Do / Doing / Done / Failed / Cancelled）分列展示，任务卡片展示 id、描述、项目、workspace、时间与状态。
3. **Task Web API**：新增 `/api/nexus/tasks*` 端点，用于列出任务、获取任务详情、获取任务对话记录（AGUI）。
4. **AGUI 对话回放**：后端将任务目录中的 `conversation.json` 转换为 AGUI 事件（至少 `MESSAGES_SNAPSHOT`），前端使用 AGUI 方式渲染任务对话。
5. **Slash Command 命名**：将 `/task` 作为主命令（创建任务），同时保留 `/think` 作为兼容别名（避免破坏现有使用习惯/脚本）。

## Scope

### In Scope
- 在现有 `nexus` 静态 Web UI 中增加 `Chat`/`Task` 双视图入口。
- 新增任务列表/详情/日志的 REST API。
- `Task` 视图可查看每个任务的 `workspace` 与最近/全部对话内容（AGUI 展示）。
- `/think` -> `/task` 的命名升级（兼容保留）。

### Out of Scope
- 任务拖拽（Drag & Drop）改状态、批量操作（首版先只读展示；需要时再扩展）。
- 任务权限/鉴权体系（沿用现有无鉴权模型）。
- 将任务执行过程实时推送到看板（首版以“已有日志/归档”回放为主）。

## Impact
- Affected specs:
  - `web-ui`（新增 Task 视图 + 视图切换）
  - `web-api`（新增 tasks 相关 API）
  - `task-storage`（新增：任务在 Redis 的存储/索引约定）
  - `slash-commands`（新增：`/task` 命令与 `/think` 兼容）
- Affected code (implementation stage):
  - `src/claude_code_api/static/nexus/*`
  - `src/claude_code_api/routers/*`
  - `src/claude_code_api/services/task_storage.py`（复用）
  - `src/claude_code_api/services/slash_command_handler.py`（命名升级）

## Success Criteria
1. 用户访问 `/nexus/` 时可在 `Chat` 与 `Task` 之间切换。
2. `Task` 视图能看到通过 `/think` 或 `/task` 创建的任务，并按状态分列显示。
3. 每个任务卡片可展示 `workspace`（若任务创建时提供）。
4. 点击任务可打开详情，并能看到该任务的对话记录（AGUI 方式展示），至少可读、可滚动、无 JS 控制台错误。
