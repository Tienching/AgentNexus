## ADDED Requirements
### Requirement: REQ-API-009 Provider/Channel Placement
Provider 与 Channel 实现 MUST 位于 `src/providers` 下，`src/runtime` 只保留核心框架模块。

#### Scenario: Provider and Channel imports
- **WHEN** 运行时加载 provider 或 channel
- **THEN** 其代码路径 MUST 位于 `src/providers/`
