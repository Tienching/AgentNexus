# Nexus 作为 agent-nexus 默认 Chat Provider — 深度分析

## 📌 目标

用户发消息时，默认走 nexus 的 AgentLoop（in-process），而非启动 claude CLI 子进程。
orchestrator skill 自动加载到 nexus 上下文，用户通过自然语言即可安排 task。

---

## 🔍 当前问题清单（feature-nexus 分支的 Gap）

### ❌ P0: `execute()` 签名不匹配 — 会在运行时崩溃

**根因**: `StreamOrchestrator.stream_agui()` 调用的是：
```python
executor.execute(request_model, exec_user=exec_user, output_format="raw")
```
但我们的 `NexusExecutor.execute()` 签名是：
```python
async def execute(self, context: RequestContext, output_format: str = "raw")
```

**所有现有 executor** 用的实际签名是：
```python
# CLIExecutor / GeminiExecutor / CodexCLIExecutor
async def execute(self, request: Any, exec_user: str = "default", output_format: str = "raw")
```

**修复**: NexusExecutor.execute() 必须改成 3 参数签名 `(request, exec_user, output_format)`，
内部将 `RequestModel` 转为 `RequestContext`。

### ❌ P0: Slash command 路由逻辑

**当前 StreamHandler._get_executor()** 逻辑：
```python
if content.startswith("/"):
    return self._executors["claude"]  # 强制走 Claude
```

当默认改成 nexus 后，slash commands 仍然会走 claude。但如果用户没装 claude CLI，
这会失败。

**方案**:
- 保留现有逻辑——slash commands 继续走 claude executor
- 或：在 NexusExecutor 中检测 slash command，委托给 CLIExecutor

### ❌ P1: Adapter 位置与导入路径

**当前**: `src/providers/nexus/adapter.py` 是独立实现
**其他 provider**: adapter 在 `src/runtime/adapters/{provider}/`

**影响**: `create_adapter("nexus")` 导入路径 `src.providers.nexus.NexusAGUIAdapter`
可以工作，但不符合项目惯例。

**决定**: 保持在 `src/providers/nexus/adapter.py`（简单，不影响功能）

### ⚠️ P1: Skill 注入 — symlink 方案的局限

**_inject_nexus_skills()** 创建 symlink:
```
{workspace}/skills/orchestrator → {nexus_root}/prompts/skills/orchestrator/
```

**问题**:
1. workspace 可能是 `~/Projects`，在里面创建 `skills/` 目录污染用户项目
2. 多用户/多 workspace 场景下 symlink 冲突
3. `_inject_nexus_skills` 在 `_create_loop()` 中执行，Pool 单例意味着只执行一次

**更好方案**: 不用 symlink，改为修改 nexus 的 `SkillsLoader` 初始化参数，
传入额外的 skills 目录。

### ⚠️ P2: config.py default_provider 改了但没用

**ProviderSettings.default_provider** 改成 `"nexus"` 了，
但 **ProviderRegistry** 用的是自己的解析逻辑（header > query > body > session > hard-coded default），
根本不读 `ProviderSettings.default_provider`。

**实际生效的默认值** 在 `src/providers/dispatcher.py` 的 `_default_provider()`。

### ⚠️ P2: nexus 初始化失败时的降级

如果 `nexus` 包没安装或配置有误，`_NexusPool._create_loop()` 会抛 ImportError。
`create_all_executors()` 在 StreamHandler.__init__() 调用——会导致**整个服务启动失败**。

**修复**: `create_all_executors()` 中 nexus 应该 try/except，失败时 log warning 而不是 crash。

---

## 🏗️ 修复计划

### Fix 1: execute() 签名匹配

```python
class NexusExecutor(BaseExecutor):
    async def execute(
        self,
        request: Any,  # RequestModel from stream handler
        exec_user: str = "default",
        output_format: str = "raw",
    ) -> AsyncGenerator[str, None]:
        # Convert RequestModel to our internal context
        if hasattr(request, 'content'):
            content = request.content
            session_id = getattr(request, 'session_id', 'default')
            cwd = getattr(request, 'cwd', None)
        else:
            content = str(request)
            session_id = 'default'
            cwd = None
        ...
```

### Fix 2: 优雅初始化

```python
def create_all_executors(*, config=None) -> dict:
    executors = {
        "claude": create_executor("claude", config=config),
        "gemini": create_executor("gemini", config=config),
        "codex":  create_executor("codex", config=config),
        "codebuddy": create_executor("codebuddy", config=config),
    }
    try:
        executors["nexus"] = create_executor("nexus", config=config)
    except Exception as e:
        logger.warning("Nexus provider unavailable: %s", e)
    return executors
```

### Fix 3: Skill 注入改用 SkillsLoader 参数

不创建 symlink，而是在创建 AgentLoop 时，修改 `SkillsLoader` 的搜索路径：

```python
# 在 _create_loop 中
nexus_skills_dir = Path(__file__).resolve().parent.parent.parent.parent / "prompts" / "skills"

# 创建 AgentLoop 后，注入额外 skill 路径
if nexus_skills_dir.exists():
    loop.context.skills.extra_skills_dirs = [nexus_skills_dir]
```

这需要在 nexus 的 `SkillsLoader` 中添加 `extra_skills_dirs` 支持，
在 `list_skills()` 中增加一个搜索层。

或者更简单的方案：通过 nexus 的 `AGENTS.md` bootstrap 文件注入 skill 描述。

### Fix 4: 默认 provider 正确生效

只需确保 `_default_provider()` 返回 `"nexus"`：

```python
def _default_provider() -> str:
    import os
    return os.environ.get("AGENT_NEXUS_DEFAULT_PROVIDER", "nexus")
```

加上 `.env` 文件配置 `AGENT_NEXUS_DEFAULT_PROVIDER=nexus` 作为部署默认。

---

## 📊 影响分析

### 改动清单

| 文件 | 改动类型 | 描述 |
|------|----------|------|
| `src/providers/nexus/executor.py` | **重写 execute()** | 匹配 3 参数签名 |
| `src/providers/dispatcher.py` | 修改 | create_all_executors 加 try/except |
| `src/providers/dispatcher.py` | 修改 | _default_provider 改成 "nexus" |
| `nexus/agent/skills.py` | 修改 | SkillsLoader 支持 extra_skills_dirs |
| `src/providers/nexus/executor.py` | 修改 | skill 注入改用 SkillsLoader 参数 |
| 测试文件 | 更新 | 适配新签名 |

### 不影响的文件
- `src/runtime/streaming/orchestrator.py` — 不变
- `src/server/services/stream_handler.py` — 不变
- `src/server/routers/chat.py` — 不变
- 所有其他 executor/adapter — 不变

---

## 🔑 核心决策点

1. **默认值用 "nexus" 还是 "claude"?**
   - 建议: 代码默认 "nexus"，通过 env var 回退到 claude

2. **Skill 注入方式: symlink vs SkillsLoader.extra_dirs vs AGENTS.md?**
   - 建议: 修改 SkillsLoader 支持 extra_dirs（最干净）

3. **Slash command 怎么处理?**
   - 建议: 保持现有逻辑（slash → claude），因为 slash commands 是 agent-nexus 特有的

4. **初始化失败降级策略?**
   - 建议: create_all_executors try/except，服务启动不因 nexus 缺失而失败
