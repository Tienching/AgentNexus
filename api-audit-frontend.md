# 前端-后端 API 一致性审计报告

> 生成时间: 2026-04-13
> 审计范围: 前端 JS (api.js, app.js, task-board-panel.js, task-components.js, inline-picker.js, list-view.js, app-data-store.js) vs 后端路由 (src/server/routers/nexus_*.py)

---

## 前端调用但后端不存在

| 前端方法 | HTTP | 路径 | 说明 |
|---|---|---|---|
| `NexusAPI.getSessionFiles` | GET | `/api/nexus/sessions/{id}/files` | 后端路由在 `nexus_files.py`，但该文件的前缀为 `/api/nexus`，路径匹配。**实际上后端存在此端点**，不是问题。 |
| `NexusAPI.getFileDownloadUrl` | GET | `/api/nexus/sessions/{id}/files/download` | 同上，后端 `nexus_files.py` 有对应端点。**实际上后端存在**。 |
| (app.js direct fetch) | GET | `/api/nexus/concurrency` | 后端 `nexus_config.py` 有 `GET /concurrency`。**存在**。 |
| (app.js direct fetch) | POST | `/api/nexus/concurrency/global` | 后端 `nexus_config.py` 有 `POST /concurrency/global`。**存在**。 |
| (app.js direct fetch) | POST | `/api/nexus/concurrency/provider` | 后端 `nexus_config.py` 有 `POST /concurrency/provider`。**存在**。 |
| (app.js direct fetch) | DELETE | `/api/nexus/concurrency/provider/{name}` | 后端 `nexus_config.py` 有 `DELETE /concurrency/provider/{name}`。**存在**。 |

> **结论：没有前端调用但后端不存在的端点。** 所有前端 API 调用都有对应后端实现。

---

## 后端存在但前端未使用

| 端点 | HTTP | 路径 | 说明 |
|---|---|---|---|
| `register_agent` | POST | `/api/nexus/agents/register` | Agent 注册端点，前端从未调用（注册由后端自动完成） |
| `agent_heartbeat` | POST | `/api/nexus/agents/{id}/heartbeat` | Agent 心跳端点，前端从未调用 |
| `get_agent` | GET | `/api/nexus/agents/{id}` | 获取单个 Agent 详情，前端只调用 list `/agents` |
| `update_agent_status` | PATCH | `/api/nexus/agents/{id}/status` | 更新 Agent 状态，前端从未调用 |
| `deregister_agent` | DELETE | `/api/nexus/agents/{id}` | 注销 Agent，前端从未调用 |
| `agent_stats` | GET | `/api/nexus/agents/stats` | Agent 统计，前端从未调用 |
| `create_team` | POST | `/api/nexus/agents/teams` | 创建 swarm team，前端从未调用 |
| `get_team_status` | GET | `/api/nexus/agents/teams/{name}` | 获取 team 状态，前端从未调用 |
| `shutdown_team` | POST | `/api/nexus/agents/teams/{name}/shutdown` | 关闭 team，前端从未调用 |
| `get_agent_mailbox` | GET | `/api/nexus/agents/teams/{name}/mailbox/{agent}` | 获取 agent 邮箱，前端从未调用 |
| `claim_team_task` | POST | `/api/nexus/agents/teams/{name}/tasks/claim` | 认领 team 任务，前端从未调用 |
| `requeue_orphan_task` | POST | `/api/nexus/tasks/{id}/requeue-orphan` | 重新入队孤立任务，前端从未调用 |
| `update_task_outcome` | PATCH | `/api/nexus/tasks/{id}/outcome` | 设置任务结果，前端从未调用 |
| `get_task_outcomes` | GET | `/api/nexus/tasks/outcomes` | 任务结果分析，前端从未调用 |
| `chat_continue_task` | POST | `/api/nexus/tasks/{id}/continue` | 继续任务对话，前端从未调用（前端用 broadcast 替代） |
| `get_session` | GET | `/api/nexus/sessions/{id}` | 获取单个 session 详情，前端从未直接调用 |
| `get_interrupted_turns` | GET | `/api/nexus/sessions/{id}/interrupted` | 获取中断轮次，前端从未调用 |
| `get_message_chain` | GET | `/api/nexus/sessions/{id}/chain/{msg_id}` | 获取 DAG 消息链，前端从未调用 |
| `recover_interrupted_turn` | POST | `/api/nexus/sessions/{id}/recover/{msg_id}` | 恢复中断轮次，前端从未调用 |
| `find_orphan_tool_results` | GET | `/api/nexus/sessions/{id}/orphans` | 查找孤立工具结果，前端从未调用 |
| `terminal_ws` | WS | `/api/nexus/terminal/{id}` | 终端 WebSocket，前端未在审计的 JS 中调用（可能由 xterm.js 组件使用） |
| `security_scan` | GET | `/api/nexus/security-scan` | 前端通过 `NexusAPI.getSecurityScan()` 调用，**已使用** |
| `get_hook_profile` | GET | `/api/nexus/security/hook-profile` | 获取 hook 安全配置，前端从未调用 |
| `update_hook_profile` | PUT | `/api/nexus/security/hook-profile` | 更新 hook 安全配置，前端从未调用 |
| `get_pending_permission_requests` | GET | `/api/nexus/security/permissions/pending` | 获取待审批权限请求，前端从未调用 |
| `approve_permission_request` | POST | `/api/nexus/security/permissions/{id}/approve` | 审批权限请求，前端从未调用 |
| `reject_permission_request` | POST | `/api/nexus/security/permissions/{id}/reject` | 拒绝权限请求，前端从未调用 |
| `get_permission_cache` | GET | `/api/nexus/security/permissions/cache` | 获取权限缓存，前端从未调用 |
| `trigger_permission_sync` | POST | `/api/nexus/security/permissions/sync` | 触发权限同步，前端从未调用 |
| `get_permissions` | GET | `/api/nexus/permissions` | 获取权限模式，前端从未调用 |
| `set_permission_mode` | PUT | `/api/nexus/permissions/mode` | 设置权限模式，前端从未调用 |
| `clear_permission_cache` | POST | `/api/nexus/permissions/cache/clear` | 清除权限缓存，前端从未调用 |
| `doctor` | GET | `/api/nexus/doctor` | 自诊断端点，前端从未调用 |
| `doctor_bundle` | GET | `/api/nexus/doctor/bundle` | 诊断打包端点，前端从未调用 |
| `get_metrics` (admin) | GET | `/api/nexus/metrics` | 管理端指标，前端从未调用 |
| `health_check` | GET | `/health` | 健康检查，前端从未调用（独立前缀，不在 /api/nexus 下） |
| `get_metrics` (health) | GET | `/metrics` | 服务指标，前端从未调用 |
| `teleport_connect` | POST | `/api/nexus/teleport/connect` | Teleport 连接，前端未在 HTTP 层调用（可能通过 WebSocket） |
| `teleport_disconnect` | POST | `/api/nexus/teleport/disconnect` | Teleport 断开，前端从未调用 |
| `teleport_execute` | POST | `/api/nexus/teleport/execute` | Teleport 执行，前端未在 HTTP 层调用 |
| `list_teleport_sessions` | GET | `/api/nexus/teleport/sessions` | Teleport 会话列表，前端从未调用 |
| `get_teleport_session` | GET | `/api/nexus/teleport/sessions/{id}` | Teleport 会话详情，前端从未调用 |
| `teleport_sync` | POST | `/api/nexus/teleport/sync` | Teleport 同步，前端从未调用 |
| `stream_teleport_output` | GET | `/api/nexus/teleport/sessions/{id}/output` | Teleport 输出流，前端从未调用 |
| `create_session` | POST | `/api/nexus/sessions` | 创建 session，前端通过 `NexusAPI.createSession()` 调用，**已使用** |
| `get_memory_state` | GET | `/api/nexus/history/memory/state` | 获取记忆状态，前端从未调用 |
| `restore_memory_context` | POST | `/api/nexus/history/sessions/{id}/restore-memory` | 恢复记忆上下文，前端从未调用 |
| `features` | GET | `/api/nexus/features` | Feature flags，前端从未调用 |
| `get_flag` | GET | `/api/nexus/features/{name}` | 获取单个 flag，前端从未调用 |
| `patch_flag` | PATCH | `/api/nexus/features/{name}` | 修改 flag，前端从未调用 |
| `reset_flag` | POST | `/api/nexus/features/{name}/reset` | 重置 flag，前端从未调用 |
| `reload_flags` | POST | `/api/nexus/features/reload` | 重载 flags，前端从未调用 |
| `list_runs` | GET | `/api/nexus/runs` | 运行列表，前端从未调用 |
| `create_run` | POST | `/api/nexus/runs` | 创建运行，前端从未调用 |
| `get_run` | GET | `/api/nexus/runs/{id}` | 获取运行详情，前端从未调用 |
| `get_run_provenance` | GET | `/api/nexus/runs/{id}/provenance` | 获取运行溯源，前端从未调用 |
| `update_run` | PUT | `/api/nexus/runs/{id}` | 更新运行，前端从未调用 |
| `eval_run` | PUT | `/api/nexus/runs/{id}/eval` | 评估运行，前端从未调用 |
| `evals_leaderboard` | GET | `/api/nexus/evals/leaderboard` | 评估排行榜，前端从未调用 |
| `create_mission` | POST | `/api/nexus/missions` | 创建任务使命，前端从未调用 |
| `approve_mission` | POST | `/api/nexus/missions/{id}/approve` | 审批使命，前端从未调用 |
| `get_mission` | GET | `/api/nexus/missions/{id}` | 获取使命详情，前端从未调用 |
| `get_mission_status` | GET | `/api/nexus/missions/{id}/status` | 获取使命状态，前端从未调用 |
| `list_missions` | GET | `/api/nexus/missions` | 列出使命，前端从未调用 |
| `cancel_mission` | POST | `/api/nexus/missions/{id}/cancel` | 取消使命，前端从未调用 |
| `pause_mission` | POST | `/api/nexus/missions/{id}/pause` | 暂停使命，前端从未调用 |
| `resume_mission` | POST | `/api/nexus/missions/{id}/resume` | 恢复使命，前端从未调用 |
| `get_mission_log` | GET | `/api/nexus/missions/{id}/log` | 获取使命日志，前端从未调用 |
| `evolution_trigger` | POST | `/api/nexus/evolution/trigger` | 进化触发，前端从未调用 |
| `evolution_synthesis` | POST | `/api/nexus/evolution/synthesis` | 进化综合，前端从未调用 |
| `evolution_status` | GET | `/api/nexus/evolution/status` | 进化状态，前端从未调用 |
| `evolution_memory` | GET | `/api/nexus/evolution/memory` | 进化记忆，前端从未调用 |
| `channels` | POST/GET | `/telegram/webhook`, `/slack/webhook`, `/feishu/webhook`, `/wecom/webhook` 等 | 通知渠道 webhook，前端从未调用（后端间通信） |
| `schedule_history` | GET | `/api/nexus/schedules/{id}/history` | 获取调度执行历史，前端 `NexusAPI.getScheduleHistory` 已定义但**在 app.js 和 task-board-panel.js 中未发现调用** |

---

## 参数/返回值不匹配

| 端点 | 前端期望 | 后端实际 | 说明 |
|---|---|---|---|
| `NexusAPI.getAuditLog` | 传递 `task_id` 参数 | 后端不接受 `task_id`，只接受 `action`, `actor`, `limit`, `offset`, `since`, `until` | `task-components.js:339` 传递了 `{ action: 'task', task_id: taskId, limit: 50 }`，但后端 `GET /api/nexus/audit` 没有 `task_id` 查询参数。前端 Timeline tab 将无法正确按 task 过滤审计事件 |
| `NexusAPI.bulkArchiveTasks` | POST body: `{ task_ids }` | 后端期望 `TaskBulkRequest` 中的 `task_ids` | **匹配** |
| `NexusAPI.bulkUnarchiveTasks` | POST body: `{ task_ids }` | 后端期望 `TaskBulkRequest` 中的 `task_ids` | **匹配** |
| `NexusAPI.bulkClearTasks` | POST body: `{ task_ids }` | 后端期望 `TaskBulkRequest` 中的 `task_ids` | **匹配** |
| `NexusAPI.bulkDeleteTasks` | POST body: `{ task_ids }` | 后端期望 `TaskBulkRequest` 中的 `task_ids` | **匹配** |
| `NexusAPI.getTaskMessages` | 传递 `tail`, `limit` | 后端 `GET /tasks/{id}/agui/messages` 接受 `limit`, `tail` | **匹配** |
| `NexusAPI.streamTaskMessages` | 传递 `tail`, `pollIntervalMs` | 后端 `GET /tasks/{id}/agui/stream` 接受 `tail`, `poll_interval_ms` | 前端使用 `pollIntervalMs`（JS camelCase），后端期望 `poll_interval_ms`（snake_case）。**前端代码已正确转换：`params.append('poll_interval_ms', ...)`，匹配** |
| `NexusAPI.getStandup` | GET 无参数 | 后端同时支持 GET 和 POST `/standup` | **匹配** |
| `NexusAPI.chatStream` | POST `/chat/stream/{execUser}?alias=...` | 后端 `POST /chat/stream/{exec_user}` 支持 `alias` 查询参数 | **匹配** |
| `NexusAPI.createSession` | POST body: 任意 payload | 后端 `nexus_sessions.py` 没有明确定义 create_session 的路由，而是由 chat stream 自动创建 | 前端 `app.js:9201` 调用 `NexusAPI.createSession({ provider, ... })`，但后端 `POST /sessions` 端点不存在于 `nexus_sessions.py`。session 创建实际通过 `POST /chat/stream/{exec_user}` 完成。**这可能导致 404 错误** |

---

## 状态值不匹配

| 前端状态 | 后端枚举 | 说明 |
|---|---|---|
| 前端 `updateTaskStatus` 注释中列出: `todo/doing/done/failed/cancelled/archived` | 后端 `TaskStatus` 枚举值（通过 `from_legacy` 归一化）: `todo`, `doing`, `done`, `failed`, `cancelled`, `archived`, `orphaned` | 前端未包含 `orphaned` 状态。`task-board-panel.js` 的 statusColumns 配置可能不显示 orphaned 任务 |
| 前端 `ListView` 有 `inbox` 作为默认分组 | 后端 `TaskStatus` 不包含 `inbox` | `list-view.js:56` 将未知状态映射到 `inbox`，但后端没有 `inbox` 状态。这是一个前端分组逻辑，不会影响 API 调用 |
| 前端 Quality Gate 审核状态: `approved`, `needs_changes`, `rejected` | 后端 `ReviewStatus` 枚举: `approved`, `needs_changes`, `rejected` | **匹配** |
| 前端 Priority 选项: `critical`, `serious`, `normal`, `low` | 后端 `TaskPriority` 枚举值 | 前端 `ListView` 增加 `low` 优先级选项（`list-view.js:101`），但 `InlinePicker` 只提供 `critical`, `serious`, `normal`（`inline-picker.js:78-82`）。需要确认后端是否支持 `low` |
| Session 状态: 前端过滤使用 `idle`, `running`, `completed`, `error` | 后端 `SessionStatus`: `idle`, `running`, `completed`, `error` | **匹配** |

---

## 功能缺失（前端有 UI 但无 API）

| UI 功能 | 说明 |
|---|---|
| 任务 Timeline 按任务 ID 过滤 | 前端 `task-components.js` 的 `renderTaskTimeline` 调用 `NexusAPI.getAuditLog({ action: 'task', task_id: taskId })`，但后端 audit 端点不支持 `task_id` 过滤。Timeline tab 可能显示非当前任务的审计事件 |
| 直接创建 Session | 前端 `NexusAPI.createSession()` 调用 `POST /api/nexus/sessions`，但后端 `nexus_sessions.py` 没有此端点。前端 UI 有创建 session 的功能，可能实际通过 chat stream 触发 |

---

## Slash 命令状态

| 命令 | 后端 | 前端支持 | 说明 |
|---|---|---|---|
| `/task` | 已注册 (handler.py) | 部分支持 | 前端有 task 创建 UI，但不是通过 slash 命令触发 |
| `/check` | 已注册 | 无 | 前端没有 slash 命令输入框或命令补全 |
| `/usage` | 已注册 | 无 | 同上 |
| `/report` | 已注册 | 无 | 同上 |
| `/cancel` | 已注册 | 无 | 同上 |
| `/trash` | 已注册 | 无 | 同上 |
| `/clear` | 已注册 | 无 | 同上 |
| `/help` | 已注册 | 无 | 同上 |
| `/chat` | 已注册 | 部分 | 前端有聊天 UI，但没有 slash 命令识别 |
| `/workspace` | 已注册 | 无 | 前端没有 workspace 切换的 slash 命令支持 |
| `/config` | 已注册 | 无 | 前端没有 config 的 slash 命令支持 |
| `/switch` | 已注册 | 无 | 前端没有 switch 的 slash 命令支持 |
| `/history` | 已注册 | 部分 | 前端有历史浏览 UI，但没有 slash 命令形式 |
| `/worktree` | 已注册 | 无 | 前端没有 worktree 的 slash 命令支持 |
| `/exit` | 已注册 | 无 | 前端没有 exit 的 slash 命令支持 |
| `/plan` | **未注册** (作为 slash command) | 部分 | 后端有 plan mode API (`/api/nexus/plan/*`) 和 `plan.py` 模块，但未列入 `SLASH_COMMANDS` 列表。前端有 Plan Mode UI（`app.js` 中 PlanModeManager） |

---

## 关键发现总结

### 严重问题 (可能导致运行时错误)

1. **`NexusAPI.createSession` → `POST /api/nexus/sessions` 不存在**：前端 `app.js:9201` 调用此方法创建 session，但后端 `nexus_sessions.py` 没有 `POST /sessions` 路由。Session 创建实际通过 `POST /chat/stream/{exec_user}` 隐式完成。这意味着前端直接创建 session 的功能会返回 404。

2. **Audit Log `task_id` 参数不被后端接受**：`task-components.js:339` 传递 `task_id` 参数给 `getAuditLog`，但后端 `GET /api/nexus/audit` 不识别此参数。Timeline tab 无法按任务过滤，会显示所有审计事件。

### 中等问题 (功能缺失但不会报错)

3. **大量后端端点没有前端 UI**：Agent lifecycle (register/heartbeat/deregister), Swarm teams, Teleport REST, Missions, Runs/Evals, Evolution, Feature flags, Permissions mode, Security hook profile, Session recovery 等完整功能模块在后端有实现但前端完全没有对应 UI。

4. **`NexusAPI.getScheduleHistory` 已定义但未使用**：`api.js:1017` 定义了此方法，但前端 JS 中未发现实际调用。Schedule 历史功能在 UI 中缺失。

5. **Slash 命令系统完全缺乏前端支持**：后端有 16 个已注册的 slash 命令，但前端没有命令输入框、自动补全或命令识别功能。`/plan` 命令也未被正式注册为 slash command。

### 轻微问题

6. **Priority `low` 不一致**：`ListView` 有 `low` 优先级选项但 `InlinePicker` 没有，需要确认后端是否支持。

7. **Orphaned 任务状态前端不处理**：后端有 `orphaned` 任务状态但前端 UI 不识别此状态。

8. **Plan Mode 重复实现**：前端 `app.js` 中 PlanModeManager 使用直接 `fetch` 调用（`app.js:7962-8056`），同时 `api.js` 也定义了 `NexusAPI.enterPlanMode` 等方法（`api.js:1130-1204`）。两套实现并存，前端 `PlanModeManager` 没有使用 `NexusAPI` 封装的方法。
