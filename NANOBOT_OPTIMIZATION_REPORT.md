# Nanobot 优化分析报告

> 对比分析：外部 nanobot (`/home/ubuntu/Projects/nanobot/nanobot/`) vs 内嵌 nanobot (`/home/ubuntu/Projects/agent-nexus_feature-dev/src/nanobot/`)
> 生成时间：2026-04-08

---

## 一、功能差异对比表

### 1. 目录结构差异

| 模块 | 外部 nanobot | 内嵌 nanobot | 差异说明 |
|------|-------------|-------------|---------|
| `channels/` | ✅ 16个文件 (base + 12个渠道 + manager + registry) | ❌ 不存在 | **重大缺失**：整个渠道系统未嵌入 |
| `cli/` | ✅ 5个文件 (commands, models, onboard, stream, __init__) | ❌ 不存在 | CLI 界面由 agent-nexus 自行实现 |
| `heartbeat/` | ✅ 存在 (service.py) | ❌ 不存在 | 心跳服务未嵌入 |
| `templates/` | ✅ 存在 (SOUL.md, TOOLS.md, HEARTBEAT.md, AGENTS.md, USER.md, memory/) | ❌ 不存在 | 模板文件未嵌入 |
| `evolve/` | ❌ 不存在 | ✅ 10个文件 | 内嵌版本独有的自进化系统 |
| `__main__.py` | ✅ 存在 | ❌ 不存在 | 外部版本可独立运行 |
| `agent/` | ✅ 6个核心文件 + tools/ | ✅ 6个核心文件 + tools/ | 结构一致 |
| `agent/tools/` | ✅ 11个工具 | ✅ 11个工具 | 文件一致 |
| `bus/` | ✅ 3个文件 | ✅ 3个文件 | 一致 |
| `command/` | ✅ 3个文件 | ✅ 3个文件 | 一致 |
| `config/` | ✅ 4个文件 | ✅ 4个文件 | 内嵌版本多了 EvolutionConfig |
| `cron/` | ✅ 3个文件 | ✅ 3个文件 | 一致 |
| `mission/` | ✅ 11个文件 | ✅ 11个文件 | 一致 |
| `providers/` | ✅ 7个文件 | ✅ 7个文件 | 一致 |
| `security/` | ✅ 2个文件 | ✅ 2个文件 | 一致 |
| `session/` | ✅ 2个文件 | ✅ 2个文件 | 一致 |
| `skills/` | ✅ 9个skill目录 | ✅ 9个skill目录 | 一致 |
| `utils/` | ✅ 3个文件 | ✅ 3个文件 | 一致 |

### 2. 代码级差异

| 文件 | 差异类型 | 详细说明 |
|------|---------|---------|
| `agent/skills.py` | **功能差异** | 内嵌版本多了 `extra_skills_dirs` 参数，支持从额外目录加载技能（如 agent-nexus 的 prompts/skills/），外部版本只有 workspace + builtin 两个来源 |
| `agent/loop.py` | 仅 import 路径差异 | `nanobot.` vs `src.nanobot.`，逻辑完全一致 |
| `agent/context.py` | 仅 import 路径差异 | 逻辑完全一致 |
| `agent/memory.py` | 仅 import 路径差异 | 逻辑完全一致 |
| `agent/subagent.py` | 仅 import 路径差异 | 逻辑完全一致 |
| `config/schema.py` | **功能差异** | 内嵌版本多了 `EvolutionConfig` 类（自进化配置），外部版本没有。其余配置完全一致 |
| `channels/base.py` | 内嵌缺失 | 基础渠道抽象类，含流式输出、权限控制、音频转录等 |
| `channels/manager.py` | 内嵌缺失 | 渠道管理器，含消息分发、重试机制、状态管理 |
| `channels/registry.py` | 内嵌缺失 | 自动发现渠道（pkgutil扫描 + entry_points插件） |
| `channels/{12个渠道}` | 内嵌缺失 | telegram, discord, slack, wechat, wecom, feishu, dingtalk, qq, whatsapp, email, matrix, mochat |
| `heartbeat/service.py` | 内嵌缺失 | 定期唤醒代理执行任务，两阶段决策（skip/run） |
| `cli/commands.py` | 内嵌缺失 | 完整的CLI命令（agent, gateway, onboard, channels, plugins, status, provider login） |
| `cli/stream.py` | 内嵌缺失 | 流式渲染（Rich Live + Markdown） |
| `cli/onboard.py` | 内嵌缺失 | 交互式配置向导 |
| `templates/*` | 内嵌缺失 | 工作区模板文件 |

---

## 二、可落地的优化建议（按优先级排序）

### P0 - 高优先级（功能缺失，影响核心能力）

#### 优化1：引入 Heartbeat 心跳服务

**现状**：内嵌 nanobot 缺少 `heartbeat/` 模块，无法定期唤醒代理执行周期性任务。agent-nexus 中的 evolve 定时任务目前依赖 cron 系统，没有心跳决策机制。

**方案**：
1. 将外部 nanobot 的 `heartbeat/service.py` 适配到 `src/nanobot/heartbeat/`
2. 修改 import 路径：`nanobot.` → `src.nanobot.`
3. 在 agent-nexus 的主入口中集成 HeartbeatService，用于 evolve 定时任务的决策
4. HeartbeatService 可替代/增强现有的 cron 触发逻辑，提供更智能的"是否有事要做"决策

**实现文件**：
- 新建 `src/nanobot/heartbeat/__init__.py`
- 新建 `src/nanobot/heartbeat/service.py`（从外部版本适配）

---

#### 优化2：引入 Channels 渠道系统

**现状**：内嵌 nanobot 缺少整个 `channels/` 模块。agent-nexus 目前通过自定义的方式（AG-UI 等）与用户交互，无法直接支持 Telegram/Discord/飞书等渠道。

**方案**：
1. 将 `channels/base.py`、`channels/manager.py`、`channels/registry.py` 适配嵌入
2. 按需引入具体渠道实现（如 `channels/telegram.py`、`channels/feishu.py`）
3. 注册机制支持从 agent-nexus 的自定义渠道扩展
4. 渠道系统可以与 agent-nexus 的 AG-UI 接口并存

**实现文件**：
- 新建 `src/nanobot/channels/__init__.py`
- 新建 `src/nanobot/channels/base.py`
- 新建 `src/nanobot/channels/manager.py`
- 新建 `src/nanobot/channels/registry.py`
- 按需新建具体渠道文件

---

### P1 - 中优先级（架构优化，提升可维护性）

#### 优化3：引入工作区模板系统

**现状**：外部 nanobot 有 `templates/` 目录，含 SOUL.md、TOOLS.md、HEARTBEAT.md、AGENTS.md、USER.md 等模板，并通过 `sync_workspace_templates()` 在启动时自动同步到工作区。内嵌版本缺少这些模板。

**方案**：
1. 将外部 nanobot 的 `templates/` 目录适配嵌入
2. 将模板文件中的 "nanobot" 品牌替换为 "agent-nexus"（或可配置）
3. 在 agent-nexus 启动时调用 `sync_workspace_templates()` 确保工作区文件完整
4. 添加 HEARTBEAT.md 模板支持心跳功能（配合优化1）

**实现文件**：
- 新建 `src/nanobot/templates/__init__.py`
- 新建 `src/nanobot/templates/SOUL.md`
- 新建 `src/nanobot/templates/TOOLS.md`
- 新建 `src/nanobot/templates/HEARTBEAT.md`
- 新建 `src/nanobot/templates/AGENTS.md`
- 新建 `src/nanobot/templates/USER.md`

---

#### 优化4：内嵌版本的 ContextBuilder 支持 Identity 定制

**现状**：`context.py` 中的 `_get_identity()` 方法硬编码返回 "nanobot 🐈" 品牌标识。agent-nexus 作为上层项目，应能定制身份信息。

**方案**：
1. 在 `ContextBuilder.__init__()` 中增加可选的 `identity_override: str | None = None` 参数
2. 若提供了 `identity_override`，则跳过默认的 `_get_identity()` 方法，直接使用定制身份
3. 在 agent-nexus 的初始化代码中传入 agent-nexus 的身份信息

**实现文件**：
- 修改 `src/nanobot/agent/context.py`

---

### P2 - 低优先级（改进体验，可选实现）

#### 优化5：SubagentManager 支持并发工具执行

**现状**：外部和内嵌版本的 `subagent.py` 中，`_run_subagent()` 方法串行执行工具调用：
```python
for tool_call in response.tool_calls:
    result = await tools.execute(tool_call.name, tool_call.arguments)
```
而主循环 `loop.py` 中使用 `asyncio.gather` 并发执行：
```python
results = await asyncio.gather(*(self.tools.execute(tc.name, tc.arguments) for tc in response.tool_calls), return_exceptions=True)
```

**方案**：将 `_run_subagent()` 中的工具执行也改为 `asyncio.gather` 并发模式，与主循环保持一致。

**实现文件**：
- 修改 `src/nanobot/agent/subagent.py`

---

#### 优化6：ChannelManager 的消息重试机制可复用

**现状**：外部 nanobot 的 `ChannelManager` 实现了 `_send_with_retry()` 方法，使用指数退避重试发送消息。agent-nexus 如果需要消息发送可靠性，可以复用这一模式。

**方案**：
1. 将重试逻辑抽象为独立的 `utils/retry.py` 工具函数
2. agent-nexus 的消息发送层可以使用相同的重试机制
3. 避免在各处重复实现退避逻辑

**实现文件**：
- 新建 `src/nanobot/utils/retry.py`

---

#### 优化7：Sync Workspace Templates 工具函数

**现状**：外部 nanobot 的 `utils/helpers.py` 中包含 `sync_workspace_templates()` 函数，用于在启动时将模板文件同步到工作区。内嵌版本的 `helpers.py` 需确认是否包含此函数。

**方案**：
1. 确认内嵌版本是否有 `sync_workspace_templates`
2. 如缺失，从外部版本适配过来
3. 修改模板源路径为 `src/nanobot/templates/`

---

## 三、各优化的具体实现方案

### 优化1实现：Heartbeat 心跳服务

```python
# src/nanobot/heartbeat/__init__.py
"""Heartbeat service for periodic agent wake-up."""
```

```python
# src/nanobot/heartbeat/service.py
# 从外部 nanobot/nanobot/heartbeat/service.py 适配
# 修改所有 import: nanobot. → src.nanobot.
# 核心逻辑不变：两阶段决策（skip/run）+ 定时触发
```

集成点：在 agent-nexus 主入口中：
```python
from src.nanobot.heartbeat.service import HeartbeatService

heartbeat = HeartbeatService(
    workspace=workspace,
    provider=provider,
    model=model,
    on_execute=on_heartbeat_execute,
    on_notify=on_heartbeat_notify,
    interval_s=config.gateway.heartbeat.interval_s,
    enabled=config.gateway.heartbeat.enabled,
    timezone=config.agents.defaults.timezone,
)
```

### 优化2实现：Channels 渠道系统

渠道系统采用渐进式引入：
1. 先引入核心框架（base + manager + registry）
2. 按需引入具体渠道
3. 在 agent-nexus 配置中添加 channels 配置项

### 优化3实现：工作区模板

从外部版本复制模板文件，修改品牌标识为可配置参数。

### 优化4实现：Identity 定制

```python
# src/nanobot/agent/context.py 修改
class ContextBuilder:
    def __init__(self, workspace: Path, timezone: str | None = None, 
                 identity_override: str | None = None):
        self.workspace = workspace
        self.timezone = timezone
        self.identity_override = identity_override
        self.memory = MemoryStore(workspace)
        self.skills = SkillsLoader(workspace)

    def build_system_prompt(self, skill_names=None):
        if self.identity_override:
            parts = [self.identity_override]
        else:
            parts = [self._get_identity()]
        # ... rest unchanged
```

### 优化5实现：Subagent 并发工具执行

```python
# src/nanobot/agent/subagent.py 修改 _run_subagent 方法
# 将串行：
#   for tool_call in response.tool_calls:
#       result = await tools.execute(tool_call.name, tool_call.arguments)
# 改为并发：
results = await asyncio.gather(*(
    tools.execute(tc.name, tc.arguments) for tc in response.tool_calls
), return_exceptions=True)

for tool_call, result in zip(response.tool_calls, results):
    if isinstance(result, BaseException):
        result = f"Error: {type(result).__name__}: {result}"
    messages.append({
        "role": "tool",
        "tool_call_id": tool_call.id,
        "name": tool_call.name,
        "content": result,
    })
```

---

## 四、总结

### 关键发现

1. **内嵌版本与外部版本核心逻辑高度一致**：agent/、bus/、command/、config/、cron/、mission/、providers/、security/、session/、skills/、utils/ 的代码逻辑完全相同，仅 import 路径不同（`nanobot.` vs `src.nanobot.`）。

2. **内嵌版本独有 evolve 系统**：这是 agent-nexus 的自进化引擎，外部 nanobot 没有对应功能。`config/schema.py` 中额外定义了 `EvolutionConfig`。

3. **内嵌版本缺少面向用户的功能**：channels（多渠道接入）、cli（交互界面）、heartbeat（心跳任务）、templates（工作区模板）这些面向终端用户的功能模块均未嵌入，因为 agent-nexus 有自己的用户交互方式。

4. **内嵌版本的 skills.py 有增强**：`extra_skills_dirs` 参数允许从额外目录加载技能，这是合理的适配性改进。

### 优化优先级矩阵

| 优化项 | 优先级 | 实现难度 | 价值 |
|-------|--------|---------|------|
| 1. Heartbeat 心跳服务 | P0 | 低 | 高 - 为 evolve 提供智能触发 |
| 2. Channels 渠道系统 | P0 | 中 | 高 - 扩展用户触达渠道 |
| 3. 工作区模板 | P1 | 低 | 中 - 规范化工作区初始化 |
| 4. Identity 定制 | P1 | 低 | 中 - 品牌可配置化 |
| 5. Subagent 并发执行 | P2 | 低 | 低 - 性能小幅提升 |
| 6. 消息重试机制 | P2 | 低 | 低 - 可靠性提升 |
| 7. sync_workspace_templates | P2 | 低 | 低 - 依赖优化3 |
