# cli Specification

## Purpose
TBD - created by archiving change refactor-agent-runtime-core. Update Purpose after archive.
## Requirements
### Requirement: VHSDK CLI Entry Point
系统 SHALL 提供 `vhsdk` CLI 工具，作为主要的命令行入口。

#### Scenario: CLI help
- **WHEN** 执行 `vhsdk --help`
- **THEN** 显示可用命令列表

### Requirement: Install Channel Command
系统 SHALL 支持 `vhsdk install channel <name>` 命令：
- 安装指定 Channel 的依赖
- 生成 Channel 配置模板
- 验证安装成功

#### Scenario: Install wecom channel
- **WHEN** 执行 `vhsdk install channel wecom`
- **THEN** 安装企微 Channel 依赖，生成配置模板

#### Scenario: Install unknown channel
- **WHEN** 执行 `vhsdk install channel unknown`
- **THEN** 显示错误：Channel "unknown" not found

### Requirement: Install Provider Command
系统 SHALL 支持 `vhsdk install provider <name>` 命令：
- 安装指定 Provider 的依赖
- 生成 Provider 配置模板

#### Scenario: Install codex provider
- **WHEN** 执行 `vhsdk install provider codex`
- **THEN** 安装 Codex Provider 依赖，生成配置模板

### Requirement: List Command
系统 SHALL 支持 `vhsdk list` 命令：
- 列出已安装的 Channels
- 列出已安装的 Providers
- 显示启用/禁用状态

#### Scenario: List installed components
- **WHEN** 执行 `vhsdk list`
- **THEN** 显示已安装的 channels 和 providers 列表

### Requirement: Config Init Command
系统 SHALL 支持 `vhsdk config init` 命令：
- 初始化配置目录
- 生成默认配置文件
- 配置存储位置：`~/.config/vhsdk/` 或项目 `config/`

#### Scenario: Initialize config
- **WHEN** 执行 `vhsdk config init`
- **THEN** 创建配置目录和默认配置文件

#### Scenario: Config already exists
- **WHEN** 配置已存在时执行 `vhsdk config init`
- **THEN** 提示是否覆盖，默认保留现有配置

