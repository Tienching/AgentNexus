# Change: Add Task Dependency Support

## Why

当前任务调度只支持基于 workspace 的并发控制（同 workspace 串行，不同 workspace 并行），无法表达任务之间的依赖关系。编排器需要能够声明"任务 B 必须等任务 A 完成才能开始"，以实现复杂的工作流编排。

## What Changes

- 在 Task 模型中新增 `depends_on` 字段，存储依赖的 task_id 列表
- 在 CreateTaskRequest API 中新增 `depends_on` 参数
- 调度器 `get_next_executable_task()` 增加依赖检查逻辑
- 新增 API 端点用于手动修改任务状态（解除阻塞）

## Impact

- Affected specs: `task-storage`, `web-api`
- Affected code:
  - `src/runtime/models/task_models.py` - Task 模型
  - `src/server/routers/nexus.py` - CreateTaskRequest, 新增 API
  - `src/runtime/execution/workspace_queue.py` - 调度逻辑
  - `src/runtime/stores/task_storage.py` - 任务状态更新
