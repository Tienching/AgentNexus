# Mission Control → Agent Nexus 功能移植分析

## 执行摘要

本文档分析了从 **Mission Control** (TypeScript/Next.js 项目) 到 **Agent Nexus** (Python 项目) 的功能移植可行性，识别出 **30 个可移植功能模块**。

---

## 项目对比概览

| 维度 | Mission Control | Agent Nexus (当前) |
|------|-----------------|-------------------|
| **语言** | TypeScript | Python |
| **框架** | Next.js 16 + React 19 | FastAPI + 自定义运行时 |
| **数据库** | SQLite (better-sqlite3) | Redis (当前) |
| **架构** | 单体 Web 应用 | 多模块 Agent Runtime SDK |
| **实时通信** | WebSocket + SSE | AG-UI SSE |
| **核心定位** | Agent 编排仪表板 | 多 Provider Agent Runtime |

---

## 可移植功能清单

### 1. Agent 管理 (3 项任务)

| ID | 功能 | MC 参考 | 移植难度 | 价值 |
|----|------|---------|----------|------|
| MC-001 | Agent 生命周期管理 | `src/app/api/agents/` | ⭐⭐⭐ | 🔥🔥🔥 |
| MC-002 | Agent 任务队列 | `src/app/api/tasks/queue/` | ⭐⭐⭐⭐ | 🔥🔥🔥 |
| MC-003 | Agent SOUL 系统 | `src/app/api/agents/[id]/soul/` | ⭐⭐⭐ | 🔥🔥 |

**说明**: MC 的 Agent 系统更加成熟，有完整的心跳、状态管理和任务分配机制。当前项目的 `nanobot/agent/` 模块可以大幅增强。

---

### 2. 任务管理 (3 项任务)

| ID | 功能 | MC 参考 | 移植难度 | 价值 |
|----|------|---------|----------|------|
| MC-004 | 6 列看板工作流 | `src/index.ts` Task 类型 | ⭐⭐⭐ | 🔥🔥🔥 |
| MC-005 | 任务评论系统 | `src/app/api/tasks/[id]/comments/` | ⭐⭐ | 🔥🔥 |
| MC-006 | 质量门禁 (Aegis) | `src/app/api/quality-review/` | ⭐⭐⭐⭐ | 🔥🔥🔥 |

**说明**: 当前任务系统比较简单，移植 MC 的完整工作流和评论系统可以大幅提升协作能力。

---

### 3. Skills 系统 (2 项任务)

| ID | 功能 | MC 参考 | 移植难度 | 价值 |
|----|------|---------|----------|------|
| MC-007 | Skills Hub + 注册表 | `src/lib/skill-registry.ts` | ⭐⭐⭐⭐ | 🔥🔥🔥 |
| MC-008 | 技能安全扫描器 | `src/app/api/security-scan/` | ⭐⭐⭐ | 🔥🔥🔥 |

**说明**: MC 的 Skills Hub 支持从 ClawdHub 和 skills.sh 安装技能，并有安全扫描。这是一个高价值移植功能。

---

### 4. 调度器 (2 项任务)

| ID | 功能 | MC 参考 | 移植难度 | 价值 |
|----|------|---------|----------|------|
| MC-009 | 自然语言转 Cron | `src/app/api/schedule-parse/` | ⭐⭐⭐ | 🔥🔥 |
| MC-010 | 模板克隆模式 | `src/lib/scheduler.ts` | ⭐⭐⭐ | 🔥🔥 |

**说明**: 当前项目已有基础 Cron 服务，移植 NLP 解析和模板克隆可以增强用户体验。

---

### 5. 活动系统 (2 项任务)

| ID | 功能 | MC 参考 | 移植难度 | 价值 |
|----|------|---------|----------|------|
| MC-011 | 活动流系统 | `src/lib/security-events.ts` | ⭐⭐ | 🔥🔥 |
| MC-012 | 通知系统 | `src/index.ts` Notification | ⭐⭐ | 🔥🔥 |

**说明**: 低难度、高价值的功能，可以增强系统的可观测性。

---

### 6. 成本追踪 (1 项任务)

| ID | 功能 | MC 参考 | 移植难度 | 价值 |
|----|------|---------|----------|------|
| MC-013 | Token 使用追踪 | `src/components/panels/CostPanel.tsx` | ⭐⭐⭐ | 🔥🔥🔥 |

**说明**: MC 有详细的 Token 使用统计和成本分析，这是一个重要的运营功能。

---

### 7. 内存系统 (1 项任务)

| ID | 功能 | MC 参考 | 移植难度 | 价值 |
|----|------|---------|----------|------|
| MC-014 | 内存浏览器 | `src/components/panels/MemoryPanel.tsx` | ⭐⭐⭐⭐ | 🔥🔥 |

**说明**: 文件系统支持的内存树和关系图谱是一个复杂但有趣的功能。

---

### 8. 安全系统 (3 项任务)

| ID | 功能 | MC 参考 | 移植难度 | 价值 |
|----|------|---------|----------|------|
| MC-015 | 安全审计系统 | `src/lib/security-events.ts` | ⭐⭐⭐⭐ | 🔥🔥🔥 |
| MC-016 | Agent 信任评分 | `src/lib/security-events.ts` | ⭐⭐⭐ | 🔥🔥 |
| MC-017 | Hook 配置文件 | `src/lib/security-events.ts` | ⭐⭐ | 🔥🔥 |

**说明**: MC 的四层安全体系 (秘密检测、MCP 审计、注入追踪、Hook 配置) 是生产部署的必备功能。

---

### 9. 通信系统 (1 项任务)

| ID | 功能 | MC 参考 | 移植难度 | 价值 |
|----|------|---------|----------|------|
| MC-018 | Agent 间消息 | `src/app/api/agents/comms/` | ⭐⭐⭐ | 🔥🔥 |

**说明**: Agent 间的直接通信能力，支持多智能体协作场景。

---

### 10. 集成系统 (3 项任务)

| ID | 功能 | MC 参考 | 移植难度 | 价值 |
|----|------|---------|----------|------|
| MC-019 | Webhooks 系统 | `src/app/api/webhooks/` | ⭐⭐⭐ | 🔥🔥🔥 |
| MC-020 | GitHub Issues 同步 | `src/lib/` GitHub 集成 | ⭐⭐⭐ | 🔥🔥 |
| MC-025 | Claude Code 集成 | `src/app/api/claude/sessions/` | ⭐⭐⭐ | 🔥🔥 |

**说明**: Webhooks 和外部集成是现代 Agent 系统的基础设施。

---

### 11. 适配器 (1 项任务)

| ID | 功能 | MC 参考 | 移植难度 | 价值 |
|----|------|---------|----------|------|
| MC-021 | 框架适配器层 | `src/lib/adapters/` | ⭐⭐⭐⭐ | 🔥🔥🔥 |

**说明**: 支持 OpenClaw、CrewAI、LangGraph、AutoGen、Claude SDK 的适配器，实现多框架兼容。

---

### 12. 工作流 (1 项任务)

| ID | 功能 | MC 参考 | 移植难度 | 价值 |
|----|------|---------|----------|------|
| MC-022 | 工作流/管道系统 | `src/app/api/pipelines/` | ⭐⭐⭐⭐ | 🔥🔥🔥 |

**说明**: 多步骤管道执行能力，支持复杂业务流程编排。

---

### 13. 评估系统 (1 项任务)

| ID | 功能 | MC 参考 | 移植难度 | 价值 |
|----|------|---------|----------|------|
| MC-023 | 四层评估框架 | `src/lib/agent-evals.ts` | ⭐⭐⭐⭐ | 🔥🔥 |

**说明**: 输出评估、追踪评估、组件评估、漂移检测的完整框架。

---

### 14. 报告系统 (1 项任务)

| ID | 功能 | MC 参考 | 移植难度 | 价值 |
|----|------|---------|----------|------|
| MC-024 | 站会报告生成 | `src/index.ts` StandupReport | ⭐⭐ | 🔥🔥 |

**说明**: 自动生成团队站会报告，展示每个 Agent 的工作状态。

---

### 15. 多租户 (1 项任务)

| ID | 功能 | MC 参考 | 移植难度 | 价值 |
|----|------|---------|----------|------|
| MC-026 | 多租户工作区 | `src/app/api/super/tenants/` | ⭐⭐⭐⭐ | 🔥🔥 |

**说明**: 完整的多租户隔离，适合 SaaS 化部署。

---

### 16. 基础设施 (4 项任务)

| ID | 功能 | MC 参考 | 移植难度 | 价值 |
|----|------|---------|----------|------|
| MC-027 | OpenAPI 3.1 规范 | `openapi.json` | ⭐⭐ | 🔥🔥 |
| MC-028 | RBAC 权限控制 | `src/lib/auth.ts` | ⭐⭐⭐ | 🔥🔥🔥 |
| MC-029 | Nexus UI 增强 | `src/components/panels/` | ⭐⭐⭐⭐ | 🔥🔥 |
| MC-030 | SQLite 存储后端 | `src/lib/db.ts` | ⭐⭐⭐ | 🔥🔥 |

**说明**: 基础设施增强，包括文档、权限、UI 和存储选项。

---

## 移植优先级建议

### 🔥 第一优先级 (立即开始)

1. **MC-001** - Agent 生命周期管理
2. **MC-004** - 6 列看板工作流
3. **MC-013** - Token 使用追踪
4. **MC-015** - 安全审计系统
5. **MC-028** - RBAC 权限控制

### 🔥🔥 第二优先级 (短期)

6. **MC-002** - Agent 任务队列
7. **MC-007** - Skills Hub
8. **MC-019** - Webhooks 系统
9. **MC-006** - 质量门禁
10. **MC-021** - 框架适配器层

### 🔥🔥🔥 第三优先级 (中期)

11. **MC-022** - 工作流系统
12. **MC-011** - 活动流系统
13. **MC-008** - 技能安全扫描
14. **MC-016** - Agent 信任评分
15. **MC-009** - 自然语言转 Cron

### 📋 第四优先级 (长期)

16-30. 其余功能模块

---

## 技术移植注意事项

### TypeScript → Python 转换

| TS 概念 | Python 等价物 | 注意事项 |
|---------|--------------|----------|
| Zustand Store | Pydantic + 自定义状态管理 | 需要手动实现响应式 |
| better-sqlite3 | sqlite3 / aiosqlite | 同步 vs 异步 API 差异 |
| Next.js API Routes | FastAPI 路由 | 路由语法相似，中间件不同 |
| React Components | 无直接等价 | 需要重新实现 Web UI |
| Zod 验证 | Pydantic | 几乎直接映射 |

### 架构差异

1. **数据库**: MC 使用 SQLite 本地优先，当前项目使用 Redis。建议保留两者作为可选项。
2. **实时通信**: MC 使用 WebSocket + SSE，当前项目使用 AG-UI SSE。可以统一为 SSE。
3. **部署模式**: MC 是单体应用，当前项目是 SDK + 服务。保持 SDK 设计，增加服务层。

---

## 文件映射参考

```
mission-control/src/ → agent-nexus/src/
├── app/api/agents/ → nanobot/agent/lifecycle.py
├── app/api/tasks/ → core/tasks/
├── lib/skill-registry.ts → nanobot/skills/registry.py
├── lib/scheduler.ts → nanobot/cron/
├── lib/security-events.ts → core/security/
├── lib/adapters/ → nanobot/adapters/
├── components/panels/ → server/static/nexus/panels/
└── lib/db.ts → core/stores/sqlite_backend.py
```

---

## 总结

从 Mission Control 可以移植 **30 个高价值功能模块**，覆盖：

- ✅ Agent 生命周期管理
- ✅ 完整的任务工作流
- ✅ Skills Hub 和安全扫描
- ✅ 安全审计和信任评分
- ✅ 多框架适配器
- ✅ 工作流和管道系统
- ✅ Webhooks 和外部集成

建议按优先级分阶段实施，先完成核心基础设施 (MC-001, MC-004, MC-028)，再逐步添加高级功能。

---

*分析日期: 2026-04-09*
*任务清单: task.json*
