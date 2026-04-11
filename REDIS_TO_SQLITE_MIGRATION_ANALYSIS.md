# Agent-Nexus Redis 迁移到 SQLite 完整分析报告

**生成时间**: 2026-04-10  
**项目根目录**: `/home/ubuntu/Projects/agent-nexus_feature-dev`  
**分析范围**: 完整的 Redis 依赖和使用场景分类

---

## 1. Redis 依赖的完整清单

### 1.1 项目配置中的 Redis 依赖

**文件**: `pyproject.toml` (第 17 行)
```toml
dependencies = [
    ...
    "redis>=5.0.0",  # Redis 客户端库（强制依赖）
    ...
]
```

**状态**: ✅ 项目强制依赖 Redis 库 v5.0.0+

### 1.2 环境配置中的 Redis 参数

**文件**: `.env.example` (第 69-93 行)
```env
# Redis 主机地址 | Redis host
REDIS_HOST=localhost

# Redis 端口 | Redis port
REDIS_PORT=6379

# Redis 数据库编号 | Redis database number
REDIS_DB=0

# Redis 密码（如不需要认证则留空） | Redis password
REDIS_PASSWORD=

# Redis Key 前缀 | Redis key prefix
REDIS_KEY_PREFIX=aona:

# Redis 连接超时（秒） | Redis connection timeout in seconds
REDIS_CONNECTION_TIMEOUT=10

# Redis Socket 超时（秒） | Redis socket timeout in seconds
REDIS_SOCKET_TIMEOUT=5
```

**状态**: ✅ 完整配置暴露了 Redis 连接参数

---

## 2. Redis 客户端实现架构

### 2.1 核心 Redis 客户端封装

**文件**: `/src/runtime/stores/redis_client.py` (347 行)

#### RedisClient 类特性

```python
class RedisClient:
    """Redis client wrapper with connection pool management"""
    
    _instance: Optional["RedisClient"] = None  # 单例模式
    _pool: Optional[ConnectionPool] = None     # 连接池
    
    # 支持的操作：
    # - 基本 KV: get/set/delete/exists
    # - Hash: hset/hget/hgetall/hdel/hexists
    # - List: lpush/rpush/lpop/rpop/lrange/llen/lrem/lset/ltrim
    # - Set: sadd/srem/smembers/sismember/scard
    # - Sorted Set: zadd/zrem/zrange/zrevrange/zrangebyscore/zcard/zscore
    # - 管道: pipeline(transaction=True)
    # - Lua 脚本: execute_script()
    # - 键模式: keys(pattern)/scan_iter()
```

**导入链**:
- `/src/core/stores/redis_client.py` → 完整实现（对 core 暴露）
- `/src/runtime/stores/redis_client.py` → 完整实现（对 runtime 暴露）
- `/src/server/services/redis_client.py` → 薄适配层（向后兼容 FastAPI）

**状态**: ❌ 三份独立实现，需要统一为单一来源

### 2.2 SQLite 后端替代方案

**文件**: `/src/core/stores/sqlite_backend.py` (408 行)

已实现的 SQLite 替代品：
- ✅ KV 存储（带 TTL）
- ✅ List 操作（push/pop/range）
- ✅ Hash 操作（set/get/getall）
- ⚠️ 简单 pub/sub（通过轮询）
- ❌ Lua 脚本执行
- ❌ 原子分布式锁
- ❌ 跨进程共享状态（不依赖 Redis）

---

## 3. Redis 使用场景完整分类

### 3.1 TaskQueue - 任务队列管理 (Redis 中心)

**文件**: `/src/core/stores/task_storage.py` (894 行, 使用 Redis)

#### 关键数据结构

| Redis 键类型 | 键模式 | 使用场景 | 替代方案 |
|-----------|--------|--------|--------|
| Hash | `task:{exec_user}:{task_id}` | 存储任务元数据 | SQLite tasks 表 |
| Sorted Set | `tasks:{exec_user}:all` | 所有任务（score=timestamp） | tasks 表 + ORDER BY created_at |
| Set | `tasks:{exec_user}:by_status:{status}` | 按状态索引任务 | tasks 表 + WHERE status=? |
| Set | `tasks:{exec_user}:by_project:{project_id}` | 按项目索引任务 | tasks 表 + WHERE project_id=? |
| Set | `tasks:{exec_user}:by_workspace:{workspace_hash}` | 按工作区索引 | tasks 表 + WHERE workspace_hash=? |
| List | `queue:{exec_user}:{workspace_hash}:todo` | TODO 任务执行队列 | tasks 表 WHERE status='TODO' ORDER BY priority |
| Set | `executing:{exec_user}:{workspace_hash}` | 正在执行的任务 | tasks 表 WHERE status='DOING' |

#### 关键操作

```python
# 任务入队（支持优先级）
def add_task(...) -> Task:
    # 存储到 Hash
    redis.hset(f"task:{exec_user}:{task_id}", task.to_redis_hash())
    # 添加到全局排序集
    redis.zadd(f"tasks:{exec_user}:all", {task_id: timestamp})
    # 按状态、项目、工作区索引
    redis.sadd(f"tasks:{exec_user}:by_status:TODO", task_id)
    # 入队（SERIOUS=头部，其他=尾部）
    redis.lpush/rpush(f"queue:{exec_user}:{workspace}:todo", task_id)

# 从队列取任务
def get_next_todo_task() -> Optional[Task]:
    task_id = redis.lpop(f"queue:{exec_user}:{workspace}:todo")
    return get_task(task_id)

# 重新入队卡住的任务
def requeue_stuck_tasks() -> int:
    # 获取所有 DOING 任务
    doing_ids = redis.smembers(f"tasks:{exec_user}:by_status:DOING")
    # 检查超时，重新入队
    for task_id in doing_ids:
        if elapsed > timeout_seconds:
            redis.srem(f"executing:{exec_user}:{workspace}", task_id)
            redis.rpush(f"queue:{exec_user}:{workspace}:todo", task_id)
```

**迁移状态**: ⚠️ 部分迁移
- ✅ `/src/runtime/stores/task_storage.py` 已改为 SQLite 实现
- ❌ `/src/core/stores/task_storage.py` 仍为 Redis 实现（core 层）

### 3.2 SessionStorage - 会话数据存储 (Redis 中心)

**文件**: `/src/core/stores/session_storage.py` (638 行, 使用 Redis)

#### 关键数据结构

| Redis 键类型 | 键模式 | 用途 | TTL | 替代方案 |
|-----------|--------|------|-----|--------|
| Hash | `session:{id}:meta` | 会话元数据 | 7 天 | sessions 表 + expires_at |
| List | `session:{id}:messages` | 消息历史 | 7 天 | messages 表 |
| Hash | `session:{id}:toolcalls` | 工具调用数据 | 7 天 | toolcalls 表 |
| List | `session:{id}:events` | AGUI 事件日志 | 7 天 | events 表 |
| String | `session:{id}:msg:{msg_id}:content` | 流式内容缓存 | 1 小时 | temp_streaming_content 表 |
| Sorted Set | `sessions:all` | 全局会话索引 | 7 天 | sessions 表 + ORDER BY updated_at |
| Sorted Set | `user:{username}:sessions` | 按用户索引 | 7 天 | sessions 表 + WHERE username=? |

#### 关键操作

```python
# 保存会话元数据
def save_session_meta(meta: SessionMeta) -> bool:
    redis.hset(f"session:{meta.id}:meta", meta.to_redis_hash())
    redis.client.expire(key, SESSION_TTL=7*24*60*60)
    redis.zadd("sessions:all", {meta.id: meta.updated_at})
    redis.zadd(f"user:{meta.username}:sessions", {meta.id: meta.updated_at})

# 获取用户的会话列表
def get_user_sessions(username: str, page: int = 1) -> Tuple[List[SessionMeta], int]:
    # 获取排序集中的会话 ID（按 updated_at 倒序）
    all_session_ids = redis.client.zrevrange(
        f"user:{username}:sessions", 0, -1
    )
    # 获取每个会话的元数据并应用筛选
    for session_id in all_session_ids:
        meta = get_session_meta(session_id)
        # 应用搜索、状态筛选

# 删除会话及所有关联数据
def delete_session(session_id: str, username: Optional[str] = None) -> bool:
    # 删除所有固定键
    redis.delete(
        f"session:{session_id}:meta",
        f"session:{session_id}:messages",
        f"session:{session_id}:toolcalls",
        f"session:{session_id}:events",
    )
    # 删除临时流式内容键（使用 scan_iter）
    for key in redis.scan_iter(f"session:{session_id}:msg:*:content"):
        redis.delete(key)
    # 从全局和用户索引中删除
    redis.zrem("sessions:all", session_id)
    redis.zrem(f"user:{username}:sessions", session_id)

# 添加消息
def add_session_message(session_id: str, message: StoredMessage) -> bool:
    redis.rpush(f"session:{session_id}:messages", message.to_json())
    redis.client.expire(key, SESSION_TTL)
    # 更新会话元数据计数和时间戳
```

**迁移状态**: ⚠️ 部分迁移
- ✅ `/src/runtime/stores/session_storage.py` 已改为 SQLite 实现（150+ 行）
- ❌ `/src/core/stores/session_storage.py` 仍为 Redis 实现

### 3.3 ScheduleStorage - 定时调度管理

**文件**: `/src/runtime/stores/schedule_storage.py` (150+ 行)

#### 关键数据结构（原 Redis）

之前使用的 Redis 结构：
- 1 个 Hash：`schedule:{schedule_id}`
- 3 个 Sorted Sets：`schedules:*:by_*`
- 2 个 Sets：`schedules:*`
- 1 个 List：`schedule:{schedule_id}:history`

**迁移状态**: ✅ 完全迁移到 SQLite
- `/src/runtime/stores/schedule_storage.py` 使用 SQLite 实现
- 迁移说明：`Replaces the multi-key Redis structure (1 hash + 3 sorted sets + 2 sets + 1 list per schedule) with a single schedules table + schedule_history table.`

### 3.4 其他小规模 Redis 使用

#### WorkspaceQueue (Redis)

**文件**: `/src/runtime/execution/workspace_queue.py` (导入 `get_redis_client`)

使用 Redis 实现跨工作区的任务队列分派。

#### 健康检查

**文件**: `/src/server/routers/health.py` (第 59-97 行)

```python
def _check_redis() -> HealthCheck:
    """Verify Redis is reachable and measure round-trip latency."""
    try:
        r = get_redis_client()
        t0 = time.monotonic()
        r.ping()  # 简单 ping 测试
        elapsed_ms = (time.monotonic() - t0) * 1000
        
        # 健康阈值：< 100ms 健康，≥ 100ms 警告
        if elapsed_ms >= 100:
            return HealthCheck(status="warning", ...)
        return HealthCheck(status="healthy", ...)
    except Exception as exc:
        return HealthCheck(status="unhealthy", ...)
```

**迁移难点**: ❌ Health check 硬编码依赖 Redis

---

## 4. 现有 SQLite 基础设施

### 4.1 核心数据库层

**文件**: `/src/runtime/stores/db.py` (243 行)

```python
class Database:
    """SQLite database manager with WAL mode and automatic migrations."""
    
    # 特性：
    # - 单例模式（_instance）
    # - 线程本地连接（threading.local）
    # - WAL 模式（并发读写）
    # - 自动迁移框架（migrations/）
    # - 事务支持（context manager）
    # - 预留信息表（_schema_version）
    
    # API:
    def conn(self):                              # 读连接
    def transaction(self):                       # 原子写事务
    def execute(sql, params) -> cursor:         # 单条执行
    def execute_fetchall(sql, params) -> [dict]
    def execute_fetchone(sql, params) -> dict
    def run_migrations(self):                    # 自动应用迁移
```

### 4.2 SQLite 迁移框架

**目录**: `/src/runtime/stores/migrations/` (13 个迁移文件)

| 迁移 | 目的 | 状态 |
|-----|------|------|
| v001_initial_kv_tables.py | 初始 KV、别名、用户配置表 | ✅ |
| v002_schedule_tables.py | 调度表（替代 Redis hash + sorted sets） | ✅ |
| v003_task_tables.py | 任务表（替代 Redis task hash + 多个 set） | ✅ |
| v004_session_tables.py | 会话、消息、工具调用表（替代 Redis hash + list） | ✅ |
| v005_run_tables.py | 运行状态表 | ✅ |
| v006_feature_flag_tables.py | 特性开关表 | ✅ |
| v007_task_workflow_columns.py | 任务工作流列 | ✅ |
| v008_activities_table.py | 活动日志表 | ✅ |
| v009_security_tables.py | 安全/审计表 | ✅ |
| v010_quality_reviews_table.py | 质量审查表 | ✅ |
| v011_task_runtime_state_columns.py | 任务运行时状态列 | ✅ |
| v012_schedule_durability_and_lock.py | 调度耐久性和锁 | ✅ |

### 4.3 SQLiteBackend - 高级接口

**文件**: `/src/core/stores/sqlite_backend.py` (408 行)

提供 Redis 兼容接口的 SQLite 实现：

```python
class SQLiteBackend:
    """SQLite-backed storage providing Redis-like interface."""
    
    # KV 操作
    def get/set/delete/exists/keys()
    
    # List 操作
    def lpush/rpush/lpop/rpop/lrange()
    
    # Hash 操作  
    def hset/hget/hgetall/hdel/hkeys()
    
    # TTL 支持
    def ttl()
    
    # 批量操作
    def flush()
```

**局限性**:
- ❌ 无 Pub/Sub（只有轮询）
- ❌ 无 Lua 脚本
- ❌ 无分布式锁
- ❌ 无 Sorted Set 操作

---

## 5. 模块使用 Redis 的完整映射

### 5.1 使用 Redis 的模块

```
Redis 使用者：
├── /src/core/stores/
│   ├── task_storage.py          ← TaskQueue（Redis）
│   ├── session_storage.py       ← SessionStorage（Redis）
│   └── redis_client.py          ← 中心客户端
├── /src/core/tasks/
│   ├── workspace_queue.py       ← get_redis_client 导入
│   └── task_executor.py         ← TaskQueue 导入
├── /src/core/archiving/
│   └── stream_archiver.py       ← SessionStorage 导入
├── /src/server/routers/
│   ├── health.py                ← get_redis_client（ping 检查）
│   ├── nexus_admin.py           ← get_redis_client
│   ├── nexus_auth.py            ← get_redis_client
│   ├── nexus_ops.py             ← get_redis_client
│   ├── nexus_security.py        ← get_redis_client
│   ├── nexus_system.py          ← get_redis_client
│   └── nexus_utils.py           ← get_redis_client
└── /src/server/services/
    ├── redis_client.py          ← 薄适配层
    └── task_storage.py          ← TaskQueue 导入
```

### 5.2 已迁移到 SQLite 的模块

```
SQLite 使用者：
├── /src/runtime/stores/
│   ├── task_storage.py          ← TaskQueue（SQLite）
│   ├── session_storage.py       ← SessionStorage（SQLite）
│   ├── schedule_storage.py      ← ScheduleStorage（SQLite）
│   ├── alias_registry.py        ← AliasRegistry（SQLite）
│   ├── user_config.py           ← UserConfigStore（SQLite）
│   ├── concurrency_config.py    ← ConcurrencyConfigStore（SQLite）
│   └── db.py                    ← 数据库管理
├── /src/runtime/execution/
│   ├── task_executor.py         ← TaskQueue（SQLite）
│   ├── scheduler.py             ← ScheduleStorage（SQLite）
│   └── workspace_queue.py       ← get_redis_client + TaskQueue
└── /src/nanobot/
    └── agent/
        ├── messaging.py         ← get_backend（SQLite）
        └── soul.py              ← get_backend（SQLite）
```

---

## 6. 迁移难点分析

### 6.1 Pub/Sub 场景（如果存在）

**结果**: ❌ 无原生 Pub/Sub 使用

Grep 搜索结果显示没有 `.subscribe()` 或 `.publish()` 调用：
```
/src/nanobot/mission/service.py: 通过 bus.publish_outbound() 实现异步通知（基于 MessageBus，非 Redis Pub/Sub）
/src/nanobot/mission/runner.py: 通知机制
/src/nanobot/agent/subagent.py: 
/src/nanobot/agent/loop.py: 
```

**结论**: 使用了 MessageBus（可能是内存或消息队列），而非 Redis Pub/Sub。

**迁移难度**: ✅ 无需处理 Pub/Sub

### 6.2 分布式锁场景

**结果**: ❌ 无明确分布式锁使用

Redis 中无 `SET ... NX` 或 `SET ... XX` 的 Lua 脚本片段。

**迁移难度**: ✅ 无需处理分布式锁

### 6.3 跨进程共享状态

**结果**: ⚠️ 部分需要

#### 任务队列（需要跨进程）
- TaskQueue 使用 Redis 的 List/Set 存储共享状态
- 执行器和调度器需要协调
- **解决方案**: SQLite 的 WAL 模式 + `PRAGMA busy_timeout` 允许并发读写

#### 会话存储（需要跨进程）
- SessionStorage 使用 Redis 存储会话元数据和消息
- 多个 FastAPI worker 可能并发访问同一个会话
- **解决方案**: SQLite 的 WAL 模式 + 连接池（thread-local）

**迁移难度**: ⚠️ 需要调整并发策略，但 SQLite WAL 模式已支持

### 6.4 健康检查中的 Redis 检查

**文件**: `/src/server/routers/health.py` (第 59-97 行)

```python
def _check_redis() -> HealthCheck:
    """Verify Redis is reachable and measure round-trip latency."""
    try:
        r = get_redis_client()
        r.ping()  # 硬编码 Redis 检查
```

**迁移困难**:
- ❌ 硬编码了 Redis 检查
- 需要改为条件性检查（检查 Redis 可用性，而非强制要求）

**解决方案**:
```python
def _check_storage() -> HealthCheck:
    """Verify primary storage is reachable (Redis or SQLite)."""
    # 优先检查 SQLite（本地文件）
    try:
        db = get_db()
        db.execute("SELECT 1")
        return HealthCheck(status="healthy", name="SQLite")
    except Exception:
        # 回退到检查 Redis（如果 SQLite 失败）
        pass
    
    # 检查 Redis（如果配置）
    if redis_enabled():
        try:
            r = get_redis_client()
            r.ping()
            return HealthCheck(status="healthy", name="Redis")
        except Exception as exc:
            return HealthCheck(status="unhealthy", ...)
    
    return HealthCheck(status="error", message="No storage backend available")
```

---

## 7. 完整迁移方案

### 7.1 第一阶段：统一 Redis 客户端

**当前问题**:
- `/src/core/stores/redis_client.py` ✅ 完整实现 (306 行)
- `/src/runtime/stores/redis_client.py` ✅ 完整实现 (347 行, 增强版)
- `/src/server/services/redis_client.py` ✅ 薄适配层

**方案**:
1. 保留 `/src/runtime/stores/redis_client.py` 为规范实现
2. 让 `/src/core/stores/redis_client.py` 重新导出（避免重复代码）
3. 更新 `/src/server/services/redis_client.py` 指向 `/src/runtime/stores/redis_client.py`

### 7.2 第二阶段：分离 Core 和 Runtime

**问题**:
- `core` 层仍依赖 Redis（Task/Session Storage）
- `runtime` 层已迁移到 SQLite

**方案**:
1. 为 Core 层创建 SQLite 实现（`/src/core/stores/task_storage_sqlite.py`）
2. 添加 Feature Flag：`USE_SQLITE_FOR_CORE_TASKS` 环境变量
3. 允许两个实现并行运行

### 7.3 第三阶段：替换健康检查

**更改**:
```python
# 之前
def _check_redis() -> HealthCheck:
    r = get_redis_client()
    r.ping()

# 之后
def _check_storage() -> HealthCheck:
    # 优先 SQLite
    db = get_db()
    db.ping()  # 或简单查询
    # 如果启用，检查 Redis
    if REDIS_ENABLED:
        r = get_redis_client()
        r.ping()
```

### 7.4 第四阶段：删除 Redis 依赖

**步骤**:
1. 移除 `pyproject.toml` 中的 `redis>=5.0.0`
2. 删除 `REDIS_*` 环境变量
3. 移除 Redis 客户端代码

---

## 8. 迁移风险和缓解策略

| 风险 | 严重性 | 缓解策略 |
|-----|-------|--------|
| SQLite 单文件性能瓶颈 | 🟡 中 | WAL 模式 + 连接池 + 异步 I/O |
| 并发写入锁定 | 🟡 中 | PRAGMA busy_timeout + 重试逻辑 |
| 任务队列顺序保证 | 🟡 中 | 使用 ROWID + 排序字段确保顺序 |
| 跨主机同步（如果分布式） | 🔴 高 | SQLite 不适合，需评估架构 |
| 临时 streaming content TTL | 🟢 低 | expires_at 列 + 后台清理 cron |
| Redis 检查硬编码 | 🟢 低 | 条件性检查 + feature flag |

---

## 9. 依赖文件清单

### Redis 相关文件（待替换/删除）

```
/src/core/stores/redis_client.py           ← 306 行，可删除或重导向
/src/runtime/stores/redis_client.py        ← 347 行，保留为规范实现
/src/server/services/redis_client.py       ← 14 行，更新为重导向
/src/core/stores/task_storage.py           ← 894 行，替换为 SQLite 版本
/src/core/stores/session_storage.py        ← 638 行，替换为 SQLite 版本
/src/server/services/task_storage.py       ← TaskQueue 包装器
/src/server/services/session_storage.py    ← SessionStorage 包装器（可能存在）
```

### SQLite 相关文件（已实现）

```
/src/runtime/stores/db.py                  ← 数据库管理（243 行）✅
/src/runtime/stores/task_storage.py        ← 任务队列（SQLite，已迁移）✅
/src/runtime/stores/session_storage.py     ← 会话存储（SQLite，已迁移）✅
/src/runtime/stores/schedule_storage.py    ← 调度存储（SQLite，已迁移）✅
/src/core/stores/sqlite_backend.py         ← 高级接口（408 行）✅
/src/runtime/stores/migrations/v00[1-9]_*.py ← 12 个迁移文件 ✅
```

---

## 10. 总结

### 现状
- **Redis 依赖**: 强制（pyproject.toml 中的 `redis>=5.0.0`）
- **迁移进度**:
  - ✅ Runtime 层已完全迁移到 SQLite（12 个迁移文件）
  - ❌ Core 层仍使用 Redis（Task/Session Storage）
  - ⚠️ 服务层暴露两套实现

### 迁移难度
- ✅ **无 Pub/Sub** → 无需异步消息传递替代品
- ✅ **无分布式锁** → 无需锁管理
- ⚠️ **跨进程状态** → SQLite WAL 已支持
- 🟡 **健康检查硬编码** → 需要条件性修改
- 🟢 **总体难度低** → 主要是代码整理和迁移框架扩展

### 建议迁移路径
1. 统一 Redis 客户端接口（模块化）
2. 为 Core 层创建 SQLite 版本（支持 feature flag 并行运行）
3. 替换健康检查为存储无关实现
4. 执行完整迁移，移除 Redis 依赖
5. 性能测试和并发压力测试

