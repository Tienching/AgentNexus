## MODIFIED Requirements
### Requirement: Provider Registry
系统 SHALL 提供 Provider 注册表，支持：
- 注册/获取 Provider 实现
- 按名称解析 Provider（claude/gemini/codex/codebuddy）
- 默认 Provider 配置

#### Scenario: Get provider by name
- **WHEN** 调用 `registry.get("codebuddy")`
- **THEN** 返回 Codebuddy Provider 实例

#### Scenario: Default provider fallback
- **WHEN** 未指定 provider
- **THEN** 使用配置的默认 provider（默认 claude）
