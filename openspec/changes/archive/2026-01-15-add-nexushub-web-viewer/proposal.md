# Proposal: Add NexusHub-Style Web Viewer for AGUI Stream

## Change ID
`add-nexushub-web-viewer`

## Summary
在现有 FastAPI 服务中新增内置的 NexusHub 风格 Web UI，用于保存并浏览 AGUI SSE Stream。将通过 AGUI 返回的 Stream 同时保存一份到 Redis，并可在网页中展示会话列表、搜索、详情回放。

## Why
- 当前 AGUI Stream 仅返回给客户端，无法持久化查看历史记录
- 需要一个 Web 界面来浏览和回放历史会话
- 参考 NexusHub 项目的实现，但作为当前项目的一部分而非独立项目
- 移除 NexusHub 中的 Terminal 和后端 Agent 配置功能（后端统一使用现有 AGUI Agent）

## What Changes
1. **Session Storage**: 将 AGUI Stream 事件保存到 Redis，复用现有 `redis_key_prefix`（默认 `aona:`）
2. **Web API**: 提供会话列表/搜索/详情/分页 REST API
3. **Web UI**: 内置静态页面，支持会话列表、搜索、点击进入详情页、实时回放

## Scope

### In Scope
1. **Session Storage**: 将 AGUI Stream 事件保存到 Redis，复用现有 `redis_key_prefix`（默认 `aona:`）
2. **Web API**: 提供会话列表/搜索/详情/分页 REST API
3. **Web UI**: 内置静态页面，支持会话列表、搜索、点击进入详情页、实时回放

### Out of Scope
- Terminal/SSH 功能（NexusHub 有但不需要）
- 后端 Agent 配置功能（使用现有 AGUI Agent）
- 用户认证系统（可选，后续扩展）
- WebSocket 实时推送（首版使用 SSE 轮询，后续可扩展）

## Design Decisions

### 1. Redis Key 结构
复用现有 `aona:` 前缀，新增以下 key 模式：
- `aona:session:{sessionId}:meta` - Hash，会话元信息
- `aona:session:{sessionId}:messages` - List，消息列表
- `aona:session:{sessionId}:toolcalls` - Hash，工具调用记录
- `aona:user:{username}:sessions` - Sorted Set，用户会话列表（按 updatedAt 排序）

### 2. 架构选择
- **同服务内置**：Web UI 作为 FastAPI 服务的一部分，通过 StaticFiles 提供静态资源
- **单页应用**：使用纯 HTML/CSS/JS 实现，无需额外构建工具
- **API 优先**：先实现 REST API，再实现 UI

### 3. Stream 归档机制
在 `StreamHandler.handle_agui_request()` 中，将 SSE 事件同时写入 Redis：
- 使用装饰器/中间件模式，不侵入现有流式逻辑
- 支持幂等写入，避免重复事件

## Dependencies
- 现有 `RedisClient` 类
- 现有 `StreamHandler` 服务
- 现有 AGUI 协议支持

## Risks & Mitigations
| Risk | Mitigation |
|------|------------|
| Redis 写入影响流式性能 | 异步写入，不阻塞 SSE 返回 |
| 大量历史数据占用存储 | 设置 TTL，默认 7 天过期 |
| 前端资源加载慢 | 使用 CDN 加载外部库（Tailwind CSS） |

## Success Criteria
1. AGUI Stream 事件自动保存到 Redis
2. Web UI 可以列出所有会话
3. 可以搜索会话标题
4. 点击会话可以查看详情和回放消息
5. 所有功能可通过 Chrome 完整验证
