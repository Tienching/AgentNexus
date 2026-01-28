## Context
现有结构包含 `agent_runtime` 顶层包以及独立的 `claude_code_api`/`gemini_cli_api`。目标是减少层级、使 provider 归类清晰。

## Goals / Non-Goals
- Goals: 扁平化目录结构；provider 归档到 `src/providers/`；保持 API 行为不变。
- Non-Goals: 改变 HTTP API、协议格式或业务语义。

## Decisions
- Decision: 运行时逻辑迁移到 `src/` 下的统一目录（如 `src/server/`、`src/runtime/`）。
- Decision: `claude_code_api`、`gemini_cli_api` 放入 `src/providers/`。
- Decision: 通过 re-export 保持旧导入路径可用（若可行）。

## Risks / Trade-offs
- 风险：大量导入路径变更；外部使用者需要同步升级。
- Mitigation: 兼容层 + 全量测试覆盖。

## Migration Plan
1. 统一目标目录结构并更新引用。
2. 添加必要的 re-export。
3. 执行测试并修复回归。

## Open Questions
- 目标目录是否统一为 `src/server/` + `src/runtime/`？
- 是否需要保留 `src/claude_code_api`、`src/gemini_cli_api` 作为兼容壳？
