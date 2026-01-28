# Proposal: Refactor to Agent Runtime Core Package

## Change ID
`refactor-agent-runtime-core`

## Summary
引入独立的 `agent_runtime` 核心包，将 provider/protocol/channel 三条变化轴彻底解耦。支持：
- **Providers**：claude / gemini / codex（未来）
- **Protocols**：AGUI / 企微协议（原 legacy）
- **Channels**：WeWork / Slack / Telegram（可插拔）
- **CLI 安装器**：`vhsdk install channel wecom` 等

## Why
1. 当前 `claude_code_api` 与 `gemini_cli_api` 存在反向依赖，新增 provider（如 codex）维护成本高。
2. 协议适配器（AGUI/legacy）直接依赖 provider raw event 格式，无法复用。
3. 需要引入 Clawdbot 的 channel 能力，但目前没有统一的 channel 插件体系。
4. 缺少 CLI 工具快速安装/配置 channel 或 provider 依赖。

## What Changes

### 1. 新建 `agent_runtime` Core 包
```
src/agent_runtime/
  events/          # 统一内部事件模型
  runtime/         # session/task/run/archiver
  providers/       # claude/gemini/codex -> events
  protocols/       # agui/wecom(企微协议) <- events
  channels/        # wecom/slack/telegram...
  routing/         # session_key / channel routing
  plugins/         # installer CLI 逻辑
```

### 2. 统一事件模型 (events)
定义内部统一事件：`TokenEvent`, `ToolCallEvent`, `MessageStartEvent`, `MessageEndEvent`, `ErrorEvent` 等。
Provider 输出统一事件流，Protocol/Channel 消费统一事件流。

### 3. Provider 层重构
- Provider 负责把 Claude/Gemini/Codex 的 raw 输出翻译成统一 events
- 现有 `providers/registry.py` 迁移到 `agent_runtime/providers/`
- `claude_code_api` / `gemini_cli_api` 变为薄接入层

### 4. Protocol 层重构
- `AGUI` / `wecom`（原 legacy）改为消费统一 events
- 移除对 provider raw event 的依赖
- 放置于 `agent_runtime/protocols/`

### 5. Channel 层引入
- 新增 `agent_runtime/channels/` 存放可插拔 channel
- 首批支持 `wecom` channel（企业微信）
- 设计基于 Clawdbot 的 channel 插件架构

### 6. CLI 安装器 (`vhsdk`)
- 命令：`vhsdk install channel wecom`
- 命令：`vhsdk install provider codex`
- 通过 `pyproject.toml` extras 或 `uv` 管理依赖
- 生成配置模板到 `~/.config/vhsdk/` 或项目 `config/`

## Scope

### In Scope
- `agent_runtime` 包结构与核心模块
- 统一事件模型
- Provider 层迁移（claude/gemini）
- Protocol 层改造（AGUI/wecom）
- WeWork channel 实现
- `vhsdk` CLI 基础命令

### Out of Scope
- codex provider 实现（Phase 4 单独做）
- Slack/Telegram channel（后续按需添加）
- WebSocket 推送
- 权限/鉴权体系

## Impact
- Affected specs:
  - `task-storage`（Task.provider 与执行）
  - `session-storage`（会话元数据）
  - `web-api`（路由与装配变化）
  - 新增 `agent-runtime` spec
  - 新增 `channels` spec
  - 新增 `cli` spec

## Risks & Mitigations
| 风险 | 缓解措施 |
|------|----------|
| 重构范围大，容易引入回归 | 分 4 个 Phase 执行，每阶段保证全量测试通过 |
| 依赖关系复杂 | 先画依赖图，确保单向依赖 |
| Channel 引入增加复杂度 | Channel 作为可选插件，不影响核心流程 |

## Phases

### Phase 1：Core 引入（不改外部行为）
- 新建 `agent_runtime/events` + `agent_runtime/providers`
- Provider 输出统一事件，原有调用路径暂时保持

### Phase 2：Protocol 解耦
- AGUI / wecom 改为消费 events
- 移除 adapter 对 provider raw event 的依赖

### Phase 3：Channel 插件
- 引入 `agent_runtime/channels/`
- 实现 WeWork channel
- routing 规则

### Phase 4：新 Provider 扩展
- codex_code_api 接入
- 验证插件体系可扩展性

## Success Criteria
1. `agent_runtime` 作为独立包，不依赖 FastAPI 或具体 API surface
2. Provider/Protocol/Channel 三层依赖关系清晰，无循环依赖
3. 现有 claude_code_api / gemini_cli_api 行为不变，测试全绿
4. `vhsdk install channel wecom` 可正常安装并生成配置
5. WeWork channel 可接收/发送消息
