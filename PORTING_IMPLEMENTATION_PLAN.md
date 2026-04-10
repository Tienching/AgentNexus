# Mission Control → Agent Nexus 移植实施计划

## 执行摘要

基于对两个代码库的深入分析，本文档提供详细的移植实施计划，包含模块依赖关系、技术方案和验收标准。

---

## 一、架构对比分析

### 1.1 技术栈对比

| 维度 | Mission Control | Agent Nexus | 移植策略 |
|------|-----------------|-------------|----------|
| **语言** | TypeScript | Python | 逻辑重写，保持 API 兼容 |
| **数据库** | SQLite (better-sqlite3) | Redis | 增加 SQLite 后端选项 |
| **Web 框架** | Next.js 16 | FastAPI | API 路由映射 |
| **实时通信** | WebSocket + SSE | AG-UI SSE | 统一使用 SSE |
| **状态管理** | Zustand | 无 (服务端) | 增加状态管理模块 |
| **ORM** | 原始 SQL | Pydantic + Redis | 增加 SQLAlchemy 可选 |

### 1.2 核心架构差异

```
Mission Control (单体应用)
├── Next.js App Router
├── SQLite (WAL mode)
├── Server EventBus (单例)
└── 101 REST API 端点

Agent Nexus (模块化 SDK)
├── FastAPI 服务层
├── Redis (当前) / SQLite (新增)
├── MessageBus (队列)
└── AG-UI SSE 协议
```

---

## 二、移植模块依赖图

```
Phase 1: 基础设施
├── MC-030 SQLite 存储后端
├── MC-028 RBAC 权限控制
└── MC-027 OpenAPI 3.1 规范

Phase 2: Agent 核心
├── MC-001 Agent 生命周期管理
│   └── 依赖: MC-028 (RBAC)
├── MC-002 Agent 任务队列
│   └── 依赖: MC-001, MC-030
└── MC-003 Agent SOUL 系统
    └── 依赖: MC-001

Phase 3: 任务管理
├── MC-004 6 列看板工作流
│   └── 依赖: MC-030
├── MC-005 任务评论系统
│   └── 依赖: MC-004, MC-001
└── MC-006 质量门禁 (Aegis)
    └── 依赖: MC-004, MC-028

Phase 4: 技能与安全
├── MC-007 Skills Hub
│   └── 依赖: MC-030
├── MC-008 技能安全扫描
│   └── 依赖: MC-007
├── MC-015 安全审计系统
│   └── 依赖: MC-001, MC-030
├── MC-016 Agent 信任评分
│   └── 依赖: MC-015
└── MC-017 Hook 配置文件
    └── 依赖: MC-015

Phase 5: 调度与活动
├── MC-009 自然语言转 Cron
├── MC-010 模板克隆模式
│   └── 依赖: MC-009
├── MC-011 活动流系统
│   └── 依赖: MC-030
└── MC-012 通知系统
    └── 依赖: MC-011

Phase 6: 集成与扩展
├── MC-013 Token 使用追踪
├── MC-014 内存浏览器
├── MC-018 Agent 间消息
│   └── 依赖: MC-001
├── MC-019 Webhooks 系统
│   └── 依赖: MC-011
├── MC-020 GitHub Issues 同步
│   └── 依赖: MC-019
├── MC-021 框架适配器层
│   └── 依赖: MC-001
├── MC-022 工作流/管道系统
│   └── 依赖: MC-004
├── MC-023 四层评估框架
├── MC-024 站会报告生成
│   └── 依赖: MC-011
├── MC-025 Claude Code 集成
└── MC-026 多租户工作区
    └── 依赖: MC-028, MC-030

Phase 7: UI 增强
└── MC-029 Nexus UI 增强
    └── 依赖: Phase 1-6
```

---

## 三、详细实施方案

### Phase 1: 基础设施 (Week 1-2)

#### MC-030: SQLite 存储后端

**目标**: 实现 SQLite 存储后端作为 Redis 的可选替代

**技术方案**:
```python
# src/core/stores/sqlite_backend.py
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class SQLiteBackend:
    """SQLite backend compatible with Redis interface"""
    
    def __init__(self, db_path: str = ".data/agent-nexus.db"):
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        
    async def get(self, key: str) -> Optional[str]:
        # 兼容 Redis 接口
        pass
        
    async def set(self, key: str, value: str, ex: Optional[int] = None):
        pass
        
    async def hgetall(self, key: str) -> Dict[str, str]:
        # Hash 操作映射到 SQLite 表
        pass
```

**数据库 Schema 移植**:
```sql
-- 从 MC migrations.ts 转换
CREATE TABLE agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    role TEXT DEFAULT 'worker',
    status TEXT DEFAULT 'offline',
    soul_content TEXT,
    config TEXT, -- JSON
    last_seen INTEGER,
    last_activity TEXT,
    created_at INTEGER DEFAULT (unixepoch()),
    updated_at INTEGER DEFAULT (unixepoch())
);

CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'inbox', -- inbox, assigned, in_progress, review, quality_review, done
    priority TEXT DEFAULT 'medium',
    assigned_to TEXT,
    project_id INTEGER,
    ticket_ref TEXT,
    created_by TEXT,
    created_at INTEGER DEFAULT (unixepoch()),
    updated_at INTEGER DEFAULT (unixepoch()),
    due_date INTEGER,
    estimated_hours REAL,
    actual_hours REAL,
    outcome TEXT,
    tags TEXT, -- JSON
    metadata TEXT -- JSON
);

CREATE TABLE activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    actor TEXT NOT NULL,
    description TEXT NOT NULL,
    data TEXT, -- JSON
    created_at INTEGER DEFAULT (unixepoch())
);

CREATE TABLE security_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    severity TEXT DEFAULT 'info',
    source TEXT,
    agent_name TEXT,
    detail TEXT,
    ip_address TEXT,
    created_at INTEGER DEFAULT (unixepoch())
);

CREATE TABLE agent_trust_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name TEXT UNIQUE NOT NULL,
    trust_score REAL DEFAULT 1.0,
    auth_failures INTEGER DEFAULT 0,
    injection_attempts INTEGER DEFAULT 0,
    rate_limit_hits INTEGER DEFAULT 0,
    secret_exposures INTEGER DEFAULT 0,
    successful_tasks INTEGER DEFAULT 0,
    failed_tasks INTEGER DEFAULT 0,
    last_anomaly_at INTEGER,
    updated_at INTEGER DEFAULT (unixepoch())
);

CREATE TABLE webhooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    secret TEXT,
    events TEXT, -- JSON array
    enabled INTEGER DEFAULT 1,
    consecutive_failures INTEGER DEFAULT 0,
    last_fired_at INTEGER,
    last_status INTEGER,
    created_at INTEGER DEFAULT (unixepoch())
);

CREATE TABLE webhook_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    webhook_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    status_code INTEGER,
    response_body TEXT,
    error TEXT,
    duration_ms INTEGER,
    attempt INTEGER DEFAULT 0,
    is_retry INTEGER DEFAULT 0,
    next_retry_at INTEGER,
    created_at INTEGER DEFAULT (unixepoch())
);
```

**验收标准**:
- [ ] SQLite 后端实现所有 Redis 核心操作 (get, set, hgetall, hset, zadd, zrange)
- [ ] 通过现有测试套件
- [ ] 性能测试: 1000 QPS 读写
- [ ] WAL 模式启用

---

#### MC-028: RBAC 权限控制

**目标**: 实现 viewer/operator/admin 三级角色权限

**技术方案**:
```python
# src/core/auth/rbac.py
from enum import Enum
from functools import wraps
from fastapi import HTTPException, Depends

class Role(str, Enum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"

# 权限层次: viewer < operator < admin
ROLE_HIERARCHY = {
    Role.VIEWER: 0,
    Role.OPERATOR: 1,
    Role.ADMIN: 2,
}

# 端点权限映射 (从 MC auth.ts 转换)
ENDPOINT_PERMISSIONS = {
    # Agents
    "GET /api/agents": Role.VIEWER,
    "POST /api/agents": Role.OPERATOR,
    "PUT /api/agents/{id}": Role.OPERATOR,
    "DELETE /api/agents/{id}": Role.ADMIN,
    
    # Tasks
    "GET /api/tasks": Role.VIEWER,
    "POST /api/tasks": Role.OPERATOR,
    "PUT /api/tasks/{id}": Role.OPERATOR,
    "PUT /api/tasks/{id}/status": Role.OPERATOR,
    
    # Skills
    "GET /api/skills": Role.VIEWER,
    "POST /api/skills": Role.OPERATOR,
    "PUT /api/skills/{id}": Role.OPERATOR,
    
    # Admin only
    "GET /api/admin/*": Role.ADMIN,
    "POST /api/super/*": Role.ADMIN,
}

def require_role(min_role: Role):
    """Decorator for FastAPI endpoints"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, current_user: User = Depends(get_current_user), **kwargs):
            if ROLE_HIERARCHY[current_user.role] < ROLE_HIERARCHY[min_role]:
                raise HTTPException(status_code=403, detail="Insufficient permissions")
            return await func(*args, current_user=current_user, **kwargs)
        return wrapper
    return decorator

# 使用示例
@app.get("/api/agents")
@require_role(Role.VIEWER)
async def list_agents(current_user: User = Depends(get_current_user)):
    pass
```

**认证方式移植**:
```python
# 支持多种认证方式 (从 MC auth.ts)
class AuthMethod(Enum):
    SESSION_COOKIE = "session"
    API_KEY = "api_key"
    GOOGLE_OAUTH = "google"
    PROXY_AUTH = "proxy"

async def get_current_user(
    session: Optional[str] = Cookie(None),
    api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None),
) -> User:
    # 尝试多种认证方式
    if api_key:
        return await authenticate_api_key(api_key)
    if authorization and authorization.startswith("Bearer "):
        return await authenticate_api_key(authorization[7:])
    if session:
        return await authenticate_session(session)
    raise HTTPException(status_code=401, detail="Authentication required")
```

**验收标准**:
- [ ] 三级角色权限控制
- [ ] 支持 Session/API Key/OAuth 认证
- [ ] 端点权限自动检查
- [ ] 集成测试覆盖

---

### Phase 2: Agent 核心 (Week 3-4)

#### MC-001: Agent 生命周期管理

**目标**: 实现 Agent 注册、心跳、状态管理

**技术方案**:
```python
# src/nanobot/agent/lifecycle.py
from datetime import datetime, timedelta
from typing import Optional
import asyncio

class AgentLifecycleManager:
    """Agent lifecycle management (ported from MC)"""
    
    HEARTBEAT_INTERVAL = 300  # 5 minutes
    OFFLINE_THRESHOLD = 600   # 10 minutes
    
    def __init__(self, db: DatabaseBackend):
        self.db = db
        self._heartbeat_task: Optional[asyncio.Task] = None
        
    async def register_agent(
        self,
        agent_id: str,
        name: str,
        role: str = "worker",
        metadata: Optional[dict] = None
    ) -> Agent:
        """Register a new agent (from MC /api/agents/register)"""
        agent = Agent(
            id=agent_id,
            name=name,
            role=role,
            status="idle",
            config=metadata or {},
            created_at=datetime.utcnow(),
        )
        await self.db.save_agent(agent)
        
        # Broadcast event
        await event_bus.broadcast("agent.created", agent.to_dict())
        
        return agent
        
    async def heartbeat(self, agent_name: str, status: str, metrics: Optional[dict] = None):
        """Update agent heartbeat (from MC /api/agents/{id}/heartbeat)"""
        now = datetime.utcnow()
        await self.db.update_agent_status(
            agent_name=agent_name,
            status=status,
            last_seen=now,
            last_activity=metrics.get("activity") if metrics else None,
        )
        
        # Update trust score for heartbeat
        await self.update_trust_score(agent_name, "heartbeat")
        
    async def check_offline_agents(self):
        """Mark agents as offline if no heartbeat (scheduler task)"""
        threshold = datetime.utcnow() - timedelta(seconds=self.OFFLINE_THRESHOLD)
        offline_agents = await self.db.find_agents_last_seen_before(threshold)
        
        for agent in offline_agents:
            if agent.status != "offline":
                await self.db.update_agent_status(agent.name, "offline")
                await event_bus.broadcast("agent.status_changed", {
                    "id": agent.id,
                    "name": agent.name,
                    "status": "offline",
                })
                
    async def start_heartbeat_monitor(self):
        """Start background task to check offline agents"""
        async def monitor():
            while True:
                await asyncio.sleep(60)  # Check every minute
                await self.check_offline_agents()
                
        self._heartbeat_task = asyncio.create_task(monitor())
        
    async def disconnect_agent(self, agent_name: str):
        """Mark agent as disconnected"""
        await self.db.update_agent_status(agent_name, "offline")
        await event_bus.broadcast("agent.disconnected", {"name": agent_name})
```

**Agent 状态机**:
```
offline → idle → busy → error
  ↑___________↓
```

**验收标准**:
- [ ] Agent 注册 API
- [ ] 心跳检测 (5分钟间隔)
- [ ] 自动离线检测 (10分钟无心跳)
- [ ] 状态变更事件广播

---

#### MC-002: Agent 任务队列

**目标**: 实现优先级任务队列和自动分配

**技术方案**:
```python
# src/nanobot/agent/queue.py
from typing import List
import heapq

class TaskQueue:
    """Priority task queue with agent assignment (ported from MC task-dispatch.ts)"""
    
    PRIORITY_WEIGHTS = {
        "critical": 0,
        "high": 1,
        "medium": 2,
        "low": 3,
    }
    
    def __init__(self, db: DatabaseBackend):
        self.db = db
        
    async def enqueue(self, task: Task) -> Task:
        """Add task to queue"""
        task.status = "inbox"
        await self.db.save_task(task)
        
        await event_bus.broadcast("task.created", task.to_dict())
        
        # Try immediate dispatch
        await self.try_dispatch(task)
        
        return task
        
    async def try_dispatch(self, task: Task) -> Optional[str]:
        """Try to dispatch task to available agent"""
        if task.assigned_to:
            # Already assigned
            return task.assigned_to
            
        # Find available agent by role
        available_agents = await self.db.find_agents(
            status="idle",
            role=task.required_role if task.required_role else None,
        )
        
        if not available_agents:
            return None
            
        # Select agent with lowest load
        agent = min(available_agents, key=lambda a: a.current_load)
        
        # Assign task
        await self.assign_task(task.id, agent.name)
        
        return agent.name
        
    async def assign_task(self, task_id: int, agent_name: str):
        """Assign task to agent"""
        await self.db.update_task(task_id, {
            "assigned_to": agent_name,
            "status": "assigned",
        })
        
        await event_bus.broadcast("task.assigned", {
            "task_id": task_id,
            "agent": agent_name,
        })
        
    async def get_agent_queue(self, agent_name: str) -> List[Task]:
        """Get pending tasks for agent (from MC /api/tasks/queue)"""
        tasks = await self.db.find_tasks(
            assigned_to=agent_name,
            status_in=["assigned", "in_progress"],
            order_by="priority",
            limit=5,
        )
        return tasks
        
    async def report_progress(
        self,
        task_id: int,
        agent_name: str,
        progress: int,
        status: str,
        output: Optional[str] = None
    ):
        """Report task progress (from MC adapter protocol)"""
        await self.db.update_task(task_id, {
            "status": status,  # in_progress, done, failed, blocked
            "progress": progress,
            "output": output,
        })
        
        if status in ["done", "failed"]:
            # Update trust score
            event_type = "task.success" if status == "done" else "task.failure"
            await self.update_trust_score(agent_name, event_type)
            
        await event_bus.broadcast("task.updated", {
            "task_id": task_id,
            "status": status,
            "progress": progress,
        })
```

**验收标准**:
- [ ] 优先级队列 (critical/high/medium/low)
- [ ] 自动任务分配
- [ ] Agent 任务拉取 API
- [ ] 进度报告和状态更新

---

### Phase 3: 任务管理 (Week 5-6)

#### MC-004: 6 列看板工作流

**目标**: 实现完整的 Kanban 工作流

**技术方案**:
```python
# src/core/tasks/kanban.py
from enum import Enum

class TaskStatus(str, Enum):
    """Kanban board columns (from MC Task interface)"""
    INBOX = "inbox"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    QUALITY_REVIEW = "quality_review"
    DONE = "done"

class KanbanBoard:
    """Kanban board management"""
    
    # 状态流转规则
    VALID_TRANSITIONS = {
        TaskStatus.INBOX: [TaskStatus.ASSIGNED, TaskStatus.DONE],
        TaskStatus.ASSIGNED: [TaskStatus.IN_PROGRESS, TaskStatus.DONE],
        TaskStatus.IN_PROGRESS: [TaskStatus.REVIEW, TaskStatus.DONE],
        TaskStatus.REVIEW: [TaskStatus.QUALITY_REVIEW, TaskStatus.DONE],
        TaskStatus.QUALITY_REVIEW: [TaskStatus.DONE],
        TaskStatus.DONE: [],
    }
    
    async def move_task(
        self,
        task_id: int,
        new_status: TaskStatus,
        user: User,
    ) -> Task:
        """Move task to new column with validation"""
        task = await self.db.get_task(task_id)
        
        # Check valid transition
        if new_status not in self.VALID_TRANSITIONS[task.status]:
            raise ValueError(f"Invalid transition: {task.status} -> {new_status}")
            
        # Quality review gate for DONE
        if new_status == TaskStatus.DONE:
            if not await self.check_quality_gate(task_id):
                raise ValueError("Task must pass quality review before marking as done")
                
        # Update status
        await self.db.update_task(task_id, {
            "status": new_status,
            "updated_at": datetime.utcnow(),
        })
        
        await event_bus.broadcast("task.status_changed", {
            "task_id": task_id,
            "from": task.status,
            "to": new_status,
            "by": user.username,
        })
        
        return await self.db.get_task(task_id)
        
    async def get_board_data(self, project_id: Optional[int] = None) -> dict:
        """Get full board data for UI"""
        columns = {}
        for status in TaskStatus:
            tasks = await self.db.find_tasks(
                status=status,
                project_id=project_id,
                order_by="priority",
            )
            columns[status.value] = [t.to_dict() for t in tasks]
            
        return {
            "columns": columns,
            "total": sum(len(t) for t in columns.values()),
        }
```

**验收标准**:
- [ ] 6 列看板数据模型
- [ ] 状态流转验证
- [ ] 拖拽排序支持
- [ ] 看板数据 API

---

#### MC-006: 质量门禁 (Aegis)

**目标**: 实现任务完成前的质量审核

**技术方案**:
```python
# src/core/quality/gates.py

class QualityGate:
    """Quality review gate (Aegis system from MC)"""
    
    async def submit_for_review(self, task_id: int, reviewer: str) -> Review:
        """Submit task for quality review"""
        review = Review(
            task_id=task_id,
            reviewer=reviewer,
            status="pending",
            created_at=datetime.utcnow(),
        )
        await self.db.save_review(review)
        
        # Update task status
        await self.db.update_task(task_id, {"status": "quality_review"})
        
        return review
        
    async def approve(self, review_id: int, notes: Optional[str] = None) -> bool:
        """Approve task quality"""
        review = await self.db.get_review(review_id)
        
        await self.db.update_review(review_id, {
            "status": "approved",
            "notes": notes,
            "completed_at": datetime.utcnow(),
        })
        
        # Move task to done
        await self.db.update_task(review.task_id, {"status": "done"})
        
        return True
        
    async def reject(self, review_id: int, reason: str) -> bool:
        """Reject task, send back to in_progress"""
        review = await self.db.get_review(review_id)
        
        await self.db.update_review(review_id, {
            "status": "rejected",
            "notes": reason,
            "completed_at": datetime.utcnow(),
        })
        
        # Send back to in_progress
        await self.db.update_task(review.task_id, {"status": "in_progress"})
        
        return True
        
    async def check_quality_gate(self, task_id: int) -> bool:
        """Check if task has passed quality review"""
        reviews = await self.db.find_reviews(
            task_id=task_id,
            status="approved",
        )
        return len(reviews) > 0
```

**验收标准**:
- [ ] 质量审核工作流
- [ ] 审核通过/拒绝
- [ ] 任务状态自动流转
- [ ] 审核历史记录

---

### Phase 4: 技能与安全 (Week 7-8)

#### MC-007: Skills Hub

**目标**: 实现技能注册表和安全扫描

**技术方案**:
```python
# src/nanobot/skills/registry.py
import httpx
from typing import List, Optional

class SkillsRegistry:
    """Skill registry client (ported from MC skill-registry.ts)"""
    
    REGISTRY_SOURCES = {
        "clawhub": "https://clawhub.ai/api",
        "skills-sh": "https://skills.sh/api",
        "awesome-openclaw": "https://raw.githubusercontent.com/VoltAgent/awesome-openclaw-skills",
    }
    
    SKILL_ROOTS = {
        "user-agents": "~/.agents/skills",
        "user-codex": "~/.codex/skills",
        "project-agents": "./.agents/skills",
        "project-codex": "./.codex/skills",
        "openclaw": "~/.openclaw/skills",
    }
    
    async def search(self, query: str, source: Optional[str] = None) -> List[Skill]:
        """Search skills across registries"""
        results = []
        
        sources = [source] if source else self.REGISTRY_SOURCES.keys()
        
        for src in sources:
            try:
                skills = await self._search_registry(src, query)
                results.extend(skills)
            except Exception as e:
                logger.warning(f"Failed to search {src}: {e}")
                
        return results
        
    async def install(self, slug: str, source: str, target_root: str) -> InstallResult:
        """Install skill from registry"""
        # Fetch skill content
        content = await self._fetch_skill(source, slug)
        
        # Security scan
        security_report = self.security_scanner.scan(content)
        if security_report.status == "rejected":
            return InstallResult(
                ok=False,
                error=f"Security check failed: {security_report.issues}",
            )
            
        # Write to disk
        target_dir = Path(self.SKILL_ROOTS[target_root]) / slug.replace("/", "_")
        target_dir.mkdir(parents=True, exist_ok=True)
        
        skill_file = target_dir / "SKILL.md"
        skill_file.write_text(content)
        
        # Save to DB
        await self.db.save_skill({
            "name": slug,
            "source": target_root,
            "path": str(target_dir),
            "content_hash": hashlib.sha256(content.encode()).hexdigest(),
            "security_status": security_report.status,
        })
        
        return InstallResult(
            ok=True,
            path=str(target_dir),
            warnings=security_report.issues if security_report.status == "warning" else [],
        )
```

#### MC-008: 技能安全扫描

**技术方案**:
```python
# src/nanobot/skills/security_scanner.py
import re
from dataclasses import dataclass
from typing import List

@dataclass
class SecurityIssue:
    severity: str  # info, warning, critical
    rule: str
    description: str
    line: Optional[int] = None

class SkillSecurityScanner:
    """Security scanner for skills (ported from MC SECURITY_RULES)"""
    
    RULES = [
        {
            "rule": "prompt-injection-system",
            "pattern": re.compile(r"\b(?:ignore\s+(?:all\s+)?previous\s+instructions?|forget\s+(?:all\s+)?(?:your\s+)?instructions?)\b", re.I),
            "severity": "critical",
            "description": "Potential prompt injection: attempts to override system instructions",
        },
        {
            "rule": "shell-exec-dangerous",
            "pattern": re.compile(r"(?:rm\s+-rf|curl\s+.*\|\s*(?:bash|sh)|wget\s+.*\|\s*(?:bash|sh))", re.I),
            "severity": "critical",
            "description": "Executable shell code with dangerous commands",
        },
        {
            "rule": "data-exfiltration",
            "pattern": re.compile(r"\b(?:send\s+(?:all\s+)?(?:data|files?|secrets?)\s+to|exfiltrate)\b", re.I),
            "severity": "critical",
            "description": "Potential data exfiltration instruction",
        },
        {
            "rule": "credential-harvesting",
            "pattern": re.compile(r"\b(?:api[_-]?key|secret|password|token)\s*[:=]\s*['\"]?\w{8,}\b", re.I),
            "severity": "warning",
            "description": "Possible hardcoded credential or secret",
        },
        {
            "rule": "ssrf-internal-network",
            "pattern": re.compile(r"https?://(?:localhost|127\.\d+\.\d+\.\d+|0\.0\.0\.0|10\.\d+\.\d+\.\d+)", re.I),
            "severity": "critical",
            "description": "Potential SSRF: attempts to contact localhost or internal network",
        },
    ]
    
    def scan(self, content: str) -> SecurityReport:
        """Scan skill content for security issues"""
        issues = []
        lines = content.split("\n")
        
        for rule in self.RULES:
            for match in rule["pattern"].finditer(content):
                # Find line number
                line_num = content[:match.start()].count("\n") + 1
                
                issues.append(SecurityIssue(
                    severity=rule["severity"],
                    rule=rule["rule"],
                    description=rule["description"],
                    line=line_num,
                ))
                
        has_critical = any(i.severity == "critical" for i in issues)
        has_warning = any(i.severity == "warning" for i in issues)
        
        status = "rejected" if has_critical else "warning" if has_warning else "clean"
        
        return SecurityReport(status=status, issues=issues)
```

**验收标准**:
- [ ] 多注册源搜索 (ClawdHub, skills.sh, Awesome)
- [ ] 12 条安全扫描规则
- [ ] SHA-256 内容校验
- [ ] 5 个技能根目录同步

---

### Phase 5-7 概要

由于篇幅限制，以下是 Phase 5-7 的核心要点:

#### Phase 5: 调度与活动
- **MC-009**: 使用 `dateparser` 库实现自然语言转 Cron
- **MC-011**: 活动流系统，参考 MC `db_helpers.logActivity()`

#### Phase 6: 集成与扩展
- **MC-019**: Webhooks 系统，指数退避重试 (30s, 5m, 30m, 2h, 8h)
- **MC-021**: 框架适配器，抽象接口支持多框架

#### Phase 7: UI 增强
- **MC-029**: 基于现有 Nexus UI 扩展面板

---

## 四、技术难点与解决方案

### 难点 1: TypeScript → Python 类型系统差异

**问题**: MC 使用 TypeScript 的严格类型，Python 的 Pydantic 需要适配

**解决方案**:
```python
# 使用 Pydantic v2 的严格模式
from pydantic import BaseModel, ConfigDict, Field

class Agent(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    
    id: int
    name: str = Field(..., min_length=1, max_length=100)
    status: Literal["offline", "idle", "busy", "error"]
    config: dict = Field(default_factory=dict)
```

### 难点 2: SQLite vs Redis 数据模型差异

**问题**: MC 使用关系型模型，当前项目使用 Redis 哈希

**解决方案**:
- 实现统一存储接口
- SQLite 作为主存储，Redis 作为缓存层

### 难点 3: 事件系统差异

**问题**: MC 使用 EventEmitter，Python 使用 asyncio

**解决方案**:
```python
# 使用 asyncio.Queue 实现事件总线
class EventBus:
    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = {}
        
    async def broadcast(self, event_type: str, data: dict):
        for callback in self._subscribers.get(event_type, []):
            asyncio.create_task(callback(data))
```

---

## 五、验收测试计划

### 集成测试

```python
# tests/integration/test_agent_lifecycle.py
async def test_agent_lifecycle():
    # Register
    agent = await lifecycle.register_agent("test-agent", "Test Agent")
    assert agent.status == "idle"
    
    # Heartbeat
    await lifecycle.heartbeat("test-agent", "busy")
    agent = await db.get_agent("test-agent")
    assert agent.status == "busy"
    
    # Offline detection
    await asyncio.sleep(11)  # Wait for offline threshold
    await lifecycle.check_offline_agents()
    agent = await db.get_agent("test-agent")
    assert agent.status == "offline"
```

### 性能测试

| 指标 | 目标 | 测试方法 |
|------|------|----------|
| 任务创建 | < 50ms | 1000 次并发 |
| 心跳处理 | < 10ms | 1000 次/秒 |
| 看板加载 | < 200ms | 1000 个任务 |
| Webhook 投递 | < 5s | 含重试 |

---

## 六、时间线

| 阶段 | 周数 | 任务 | 产出 |
|------|------|------|------|
| Phase 1 | 1-2 | 基础设施 | SQLite 后端 + RBAC |
| Phase 2 | 3-4 | Agent 核心 | 生命周期 + 队列 |
| Phase 3 | 5-6 | 任务管理 | Kanban + 质量门禁 |
| Phase 4 | 7-8 | 技能与安全 | Skills Hub + 安全扫描 |
| Phase 5 | 9-10 | 调度与活动 | Cron NLP + 活动流 |
| Phase 6 | 11-14 | 集成与扩展 | Webhooks + 适配器 |
| Phase 7 | 15-16 | UI 增强 | Nexus 面板 |

**总计**: 16 周 (4 个月)

---

*计划版本: 1.0*
*更新日期: 2026-04-09*
