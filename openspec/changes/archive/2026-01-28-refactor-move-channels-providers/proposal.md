# Change: Move runtime channels/providers under src/providers

## Why
当前 `src/runtime` 下仍包含 `channels/` 与 `providers/`，与“runtime 为内核、providers 为扩展层”的分层目标不一致。将 `runtime/channels` 与 `runtime/providers` 迁移到 `src/providers/` 可减少层级、统一扩展层入口。

## What Changes
- **BREAKING**: `src/runtime/channels` → `src/providers/channels`
- **BREAKING**: `src/runtime/providers` → `src/providers/runtime`
- 更新所有导入路径与注册逻辑，保持行为不变

## Impact
- Affected specs: `web-api`
- Affected code: `src/runtime/*`, `src/providers/*`, tests
