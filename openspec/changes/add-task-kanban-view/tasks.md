# Tasks: Add Task Kanban View

## 1. Slash Commands
- [x] **1.1** 将 `/task` 作为创建任务主命令，并保留 `/think` 兼容别名
  - 验证：更新/新增单元测试覆盖 `/task` 与 `/think` 两种输入

## 2. Task Web API
- [x] **2.1** 在 `nexus` API 下新增任务列表端点
  - `GET /api/nexus/tasks`：支持按 `agent_name`（默认值）、`status`、`project_id`、`workspace`、`search` 过滤
  - 验证：集成测试覆盖分页/过滤（或最小可用的列表返回）

- [x] **2.2** 新增任务详情端点
  - `GET /api/nexus/tasks/{task_id}`：返回任务详情（含 workspace、时间、错误信息）
  - 验证：404/不存在场景

- [x] **2.3** 新增任务对话记录端点（AGUI）
  - `GET /api/nexus/tasks/{task_id}/agui/messages`：返回 `MESSAGES_SNAPSHOT`（支持 `tail`/`limit`）
  - 验证：日志缺失/解析失败的错误处理

## 3. Web UI (Chat/Task 双视图)
- [x] **3.1** 将现有会话浏览页面在 UI 上命名为 `Chat` 视图并保持行为不变
  - 验证：Chat 视图功能回归（列表、搜索、详情、删除）

- [x] **3.2** 新增 `Task` 视图 Kanban 看板
  - To Do / Doing / Done / Failed / Cancelled 五列
  - 任务卡片展示：id、描述、project、workspace、更新时间

- [x] **3.3** 新增任务详情面板，并展示任务对话（AGUI）
  - 点击任务卡片打开详情
  - 通过 AGUI messages snapshot 渲染对话内容

## 4. Validation
- [x] **4.1** 补充/更新测试
  - 单元测试：slash commands、task storage（必要时）
  - 集成测试：tasks API

- [x] **4.2** 本 change 提案通过 `openspec validate add-task-kanban-view --strict`
