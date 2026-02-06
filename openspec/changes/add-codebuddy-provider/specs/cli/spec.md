## MODIFIED Requirements
### Requirement: Install Provider Command
系统 SHALL 支持 `vhsdk install provider <name>` 命令：
- 安装指定 Provider 的依赖
- 生成 Provider 配置模板

#### Scenario: Install codex provider
- **WHEN** 执行 `vhsdk install provider codex`
- **THEN** 安装 Codex Provider 依赖，生成配置模板

#### Scenario: Install codebuddy provider
- **WHEN** 执行 `vhsdk install provider codebuddy`
- **THEN** 安装 Codebuddy Provider 依赖，生成配置模板
