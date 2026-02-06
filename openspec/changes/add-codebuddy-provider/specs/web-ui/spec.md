## ADDED Requirements
### Requirement: REQ-UI-012 Agent Selector Includes Codebuddy
Nexus UI MUST 在 Agent/Model 选择器中展示 `codebuddy` 相关选项。

#### Scenario: Select Codebuddy in New Chat
- **Given** 用户打开 New Chat
- **When** 选择 Model 下拉框
- **Then** 列表中包含 `codebuddy`/`codebuddy-internal`

#### Scenario: Select Codebuddy in New Task
- **Given** 用户打开 New Task
- **When** 选择 Model 下拉框
- **Then** 列表中包含 `codebuddy`/`codebuddy-internal`
