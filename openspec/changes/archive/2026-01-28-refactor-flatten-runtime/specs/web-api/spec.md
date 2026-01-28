## ADDED Requirements
### Requirement: REQ-API-008 Flattened Runtime Layout
运行时与 provider 目录结构 MUST 扁平化到 `src/` 下，并保证 Web API 行为与现有规范一致。

#### Scenario: Provider packages reside under src/providers
- **WHEN** 运行时加载 provider
- **THEN** provider 包路径 MUST 位于 `src/providers/`
