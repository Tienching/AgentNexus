## ADDED Requirements
### Requirement: REQ-API-014 Provider Routing for Chat Stream
系统 MUST 在 `/chat/stream` 入口支持 `provider=codebuddy` 的解析与路由。

#### Scenario: Resolve Codebuddy provider label
- **Given** 请求体包含 `provider: "codebuddy"`
- **When** 调用 `/chat/stream/{exec_user}`
- **Then** Provider Registry 解析为 `codebuddy` 并路由到对应执行链路
