# Implementation Tasks

## 1. Data Model Changes
- [x] 1.1 在 `Task` 模型中添加 `depends_on: List[str] = []` 字段
- [x] 1.2 更新 `to_redis_hash()` 和 `from_redis_hash()` 处理 `depends_on` 序列化

## 2. API Changes
- [x] 2.1 在 `CreateTaskRequest` 中添加 `depends_on` 参数
- [x] 2.2 在 `create_task` 端点中处理 `depends_on` 参数
- [x] 2.3 新增 `PATCH /api/nexus/tasks/{task_id}/status` 端点用于手动修改任务状态

## 3. Scheduler Changes
- [x] 3.1 在 `WorkspaceQueueManager.get_next_executable_task()` 中添加依赖检查
- [x] 3.2 实现 `_check_dependencies_satisfied()` 方法：检查所有依赖任务是否为 DONE 状态

## 4. Testing
- [x] 4.1 添加 Task 模型 `depends_on` 序列化测试
- [x] 4.2 添加依赖调度逻辑单元测试
- [x] 4.3 添加 API 端点集成测试
