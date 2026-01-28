## Context
需要在保持统一入口与 AGUI 行为不变的前提下，新增 Gemini CLI stream-json 的解析与事件映射。Gemini CLI 输出示例包含如下事件类型：
- `init`（会话/模型信息）
- `message`（role 为 user/assistant 的文本）
- `tool_use`（工具调用：tool_name/tool_id/parameters）
- `tool_result`（工具结果：tool_id/status/output）

## Goals / Non-Goals
- Goals:
  - 支持 Gemini CLI stream-json 输入并输出 AGUI 事件流。
  - 统一入口在不改变外部 API 的前提下选择 Claude 或 Gemini 执行链路。
  - 工具调用事件在 AGUI 中保持一致的 `toolCallId/toolCallName/args/result` 语义。
- Non-Goals:
  - 修改 AGUI 事件 schema。
  - 变更已有路由或对外 API 结构。

## Decisions
- Decision: 为 Gemini 新增独立 `gemini_cli_api` 模块与适配器（结构对齐 `claude_code_api`），在统一入口中按 provider 选择执行器与解析链路。
- Decision: Gemini 事件映射规则（保持与 Claude Code AGUI 输出语义一致）：
  - `init` -> `RUN_STARTED`
  - `message`(role=assistant) -> `TEXT_MESSAGE_START` + `TEXT_MESSAGE_CONTENT` + `TEXT_MESSAGE_END`
  - `tool_use` -> `TOOL_CALL_START` + `TOOL_CALL_ARGS`（参数 JSON 字符串）
  - `tool_result` -> `TOOL_CALL_END`（包含 result）+ `TOOL_CALL_RESULT/END`
  - `message`(role=user) 默认忽略（请求体已包含用户消息），如需保留可在实现期调整
- Decision: 统一入口通过 query 参数 `provider=gemini` 选择 Gemini 链路（默认 Claude）。

## Risks / Trade-offs
- Gemini CLI 的事件可能存在新增类型或增量输出差异，需要在解析层做容错与回退。
- `message`(role=user) 是否需要转为 AGUI 事件存在歧义，需在实现时验证前端消费逻辑。

## Migration Plan
- 增量新增模块与路由分支，不影响现有 Claude 链路。
- 通过测试与手动流式回放验证 AGUI 兼容性。

## Open Questions
- 是否需要在 AGUI 事件流中保留 `message`(role=user)？
