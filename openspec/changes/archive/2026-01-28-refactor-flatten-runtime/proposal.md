# Change: Flatten runtime layout and move providers under src/providers

## Why
当前 `agent_runtime` 作为顶层运行时包导致结构分散。将运行时逻辑解压到 `src/` 下并把 `claude_code_api`、`gemini_cli_api` 放到 `providers/` 可减少层级、让 provider 更对称。

## What Changes
- **BREAKING**: 移除 `agent_runtime` 顶层包结构，运行时模块下沉到 `src/` 直接目录或 `src/server/`。
- **BREAKING**: 将 `claude_code_api`、`gemini_cli_api` 迁移到 `src/providers/`。
- 通过 re-export 或兼容层保持旧导入路径尽量可用（可选）。

## Impact
- Affected specs: `web-api`
- Affected code: `src/agent_runtime/*`, `src/claude_code_api/*`, `src/gemini_cli_api/*`
