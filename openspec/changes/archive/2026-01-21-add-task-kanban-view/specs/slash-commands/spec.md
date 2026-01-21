## ADDED Requirements

### Requirement: REQ-SC-001 Create Task via /task
系统 MUST 支持用户使用 `/task` 创建任务。

#### Scenario: Create task using /task
- **Given** 用户输入 `/task 修复登录页面异常 -w /path/to/ws`
- **When** 系统解析 slash command
- **Then** 系统创建一个新任务并返回任务 ID
- **And** 任务包含 `workspace` 字段

### Requirement: REQ-SC-002 Backward Compatible /think Alias
系统 MUST 保留 `/think` 作为 `/task` 的兼容别名。

#### Scenario: Create task using /think
- **Given** 用户输入 `/think 修复登录页面异常`
- **When** 系统解析 slash command
- **Then** 系统创建一个新任务
- **And** 返回格式与 `/task` 行为等价（除文案提示外）
