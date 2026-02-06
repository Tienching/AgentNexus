# Change: Add Codebuddy Provider

## Why
需要像 `codex` 一样接入 `codebuddy` CLI（`--output-format stream-json`），以便统一通过 AG-UI/Web API 与 Nexus UI 调用。

## What Changes
- 新增 `codebuddy` Provider 支持（CLI 执行器、AG-UI 适配器、路由/注册）。
- Web API 支持 `provider=codebuddy` 的解析与路由。
- Nexus UI/Task 创建中可选择 `codebuddy` 模型。
- CLI 安装命令支持 `vhsdk install provider codebuddy`。

## Impact
- Affected specs: `agent-runtime`, `stream-adapters`, `web-api`, `web-ui`, `cli`
- Affected code: `src/providers/*`, `src/runtime/adapters/*`, `src/server/services/stream_handler.py`, `src/server/providers/registry.py`, `src/server/routers/nexus.py`, `src/runtime/plugins/*`

## Assumptions
- CLI 命令为 `codebuddy`，并支持 `codebuddy -p "" --output-format stream-json`。
- Provider 名称统一为 `codebuddy`（不再需要 `codebuddy-internal` 变体）。
