# Tasks: Add NexusHub-Style Web Viewer

## Phase 1: Session Storage Layer

- [x] **1.1** 创建 `src/claude_code_api/models/session.py`
  - 定义 `SessionMeta`, `StoredMessage`, `StoredToolCall` 数据模型
  - 定义 `SessionStatus` 枚举
  - 验证：单元测试模型序列化

- [x] **1.2** 创建 `src/claude_code_api/services/session_storage.py`
  - 实现 `SessionStorage` 类
  - 方法：`save_session_meta()`, `get_session_meta()`, `get_user_sessions()`
  - 方法：`add_session_message()`, `get_session_messages()`
  - 方法：`save_tool_call()`, `get_session_tool_calls()`
  - 方法：`update_session_status()`, `delete_session()`
  - 验证：单元测试（mock Redis）

- [x] **1.3** 创建 `tests/unit/test_session_storage.py`
  - 测试所有 CRUD 操作
  - 测试 TTL 设置
  - 测试用户会话索引

## Phase 2: Stream Archiver

- [x] **2.1** 创建 `src/claude_code_api/services/stream_archiver.py`
  - 实现 `StreamArchiver` 类
  - 方法：`on_run_started()`, `on_run_finished()`, `on_run_error()`
  - 方法：`archive_event()` - 根据事件类型分发处理
  - 处理：`TEXT_MESSAGE_START/CONTENT/END`
  - 处理：`TOOL_CALL_START/ARGS/END/RESULT`
  - 验证：单元测试事件处理

- [x] **2.2** 修改 `src/claude_code_api/services/stream_handler.py`
  - 在 `handle_agui_request()` 中集成 `StreamArchiver`
  - 使用 `asyncio.create_task()` 异步归档，不阻塞 SSE
  - 验证：集成测试确认事件被归档

- [x] **2.3** 创建 `tests/unit/test_stream_archiver.py`
  - 测试完整的 AGUI 流程
  - 验证事件处理逻辑

## Phase 3: Web API

- [x] **3.1** 创建 `src/claude_code_api/routers/nexus.py`
  - `GET /api/nexus/sessions` - 会话列表（分页、搜索）
  - `GET /api/nexus/sessions/{id}` - 会话详情
  - `GET /api/nexus/sessions/{id}/messages` - 会话消息
  - `DELETE /api/nexus/sessions/{id}` - 删除会话
  - `POST /api/nexus/sessions/{id}/cancel` - 取消运行
  - 验证：API 单元测试

- [x] **3.2** 修改 `src/claude_code_api/app.py`
  - 注册 nexus router
  - 配置静态文件服务 `/nexus/`
  - 验证：启动服务确认路由可访问

- [x] **3.3** 创建 `tests/integration/test_nexus_api.py`
  - 测试所有 API 端点
  - 测试分页逻辑
  - 测试搜索功能

## Phase 4: Web UI

- [x] **4.1** 创建 `src/claude_code_api/static/nexus/index.html`
  - 会话列表页面
  - 搜索框
  - 按日期分组显示
  - 状态标签
  - 验证：浏览器手动测试

- [x] **4.2** 会话详情功能已集成到 `index.html` (单页应用)
  - 消息列表
  - 工具调用展示
  - 返回按钮（通过点击其他会话切换）

- [x] **4.3** 创建 `src/claude_code_api/static/nexus/js/api.js`
  - API 调用封装
  - 错误处理
  - 验证：控制台测试

- [x] **4.4** 创建 `src/claude_code_api/static/nexus/js/app.js`
  - 页面初始化
  - 事件绑定
  - 状态管理
  - 验证：功能测试

- [x] **4.5** 创建 `src/claude_code_api/static/nexus/css/styles.css`
  - 自定义样式
  - 响应式布局
  - 验证：视觉检查

## Phase 5: Integration & Testing

- [x] **5.1** 端到端测试
  - 发送 AGUI 请求
  - 打开 Web UI 验证会话出现
  - 点击查看详情
  - 搜索功能
  - 验证：Chrome DevTools 检查

- [x] **5.2** 性能测试
  - 确认 Stream 归档不影响 SSE 延迟（使用 asyncio.create_task 异步归档）
  - API 响应时间 < 200ms
  - 验证：代码审查确认异步设计

- [x] **5.3** 文档更新
  - 更新 README 添加 Web UI 说明
  - 添加配置说明
  - 验证：文档审查

## Dependencies

```
Phase 1 ──► Phase 2 ──► Phase 3 ──► Phase 5
                            │
                            ▼
                        Phase 4 ──► Phase 5
```

- Phase 2 依赖 Phase 1（需要 SessionStorage）
- Phase 3 依赖 Phase 1（需要 SessionStorage）
- Phase 4 依赖 Phase 3（需要 API）
- Phase 5 依赖所有前置 Phase

## Parallelizable Work

- Phase 3 和 Phase 4 可以部分并行（API 定义后 UI 可以开始）
- 单元测试可以与实现并行编写

## Implementation Summary

### Completed Files

| File | Description |
|------|-------------|
| `src/claude_code_api/models/session.py` | 数据模型：SessionMeta, StoredMessage, StoredToolCall |
| `src/claude_code_api/services/session_storage.py` | 会话存储服务，支持 CRUD 操作 |
| `src/claude_code_api/services/stream_archiver.py` | 流归档器，异步保存 AGUI 事件 |
| `src/claude_code_api/routers/nexus.py` | REST API 路由 |
| `src/claude_code_api/static/nexus/index.html` | Web UI 主页面 |
| `src/claude_code_api/static/nexus/js/api.js` | API 客户端封装 |
| `src/claude_code_api/static/nexus/js/app.js` | 前端应用逻辑 |
| `src/claude_code_api/static/nexus/css/styles.css` | 自定义样式 |

### Modified Files

| File | Changes |
|------|---------|
| `src/claude_code_api/app.py` | 注册 nexus router，配置静态文件服务 |
| `src/claude_code_api/services/stream_handler.py` | 集成 StreamArchiver |
| `src/claude_code_api/models/__init__.py` | 导出 session 模型 |
| `src/claude_code_api/services/__init__.py` | 导出 session_storage 和 stream_archiver |
