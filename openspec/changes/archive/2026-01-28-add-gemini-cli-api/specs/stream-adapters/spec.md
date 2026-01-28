## ADDED Requirements
### Requirement: REQ-STA-001 Gemini CLI Stream-JSON to AGUI
系统 MUST 支持将 Gemini CLI `--output-format stream-json` 的事件流转换为 AGUI 事件流。

#### Scenario: Convert Gemini tool calls and assistant text
- **Given** Gemini stream-json 依次产生 `init`、`message`(assistant)、`tool_use`、`tool_result`
- **When** 统一入口处理该请求并输出 AGUI SSE
- **Then** 输出包含 `RUN_STARTED`、`TEXT_MESSAGE_*`、`TOOL_CALL_*`、`TOOL_CALL_RESULT_*` 等事件
- **And** `toolCallId/toolCallName/args/result` 与 Gemini 事件保持一致

### Requirement: REQ-STA-002 Provider Routing for Unified Entry
系统 MUST 在统一入口支持选择 Gemini 执行链路。

#### Scenario: Route to Gemini via provider query
- **Given** 请求携带 `provider=gemini` 且协议为 AGUI
- **When** 调用 `/chat/stream`
- **Then** 系统使用 Gemini CLI 执行器与对应适配器处理流式输出
