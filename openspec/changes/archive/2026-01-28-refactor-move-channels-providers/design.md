## Context
`runtime` 仍包含 `providers/` 与 `channels/`，导致扩展层分散。目标是让 `src/providers` 成为所有外部扩展的统一容器。

## Goals / Non-Goals
- Goals: 将 `channels` 与 `providers` 迁移到 `src/providers/`，保持 API 行为不变。
- Non-Goals: 改变协议语义、HTTP API、业务逻辑。

## Decisions
- Decision: `src/runtime/providers` → `src/providers/runtime`
- Decision: `src/runtime/channels` → `src/providers/channels`

## Risks / Trade-offs
- 风险：导入路径变更广泛。
- Mitigation: 批量替换 + 全量测试。

## Migration Plan
1. 迁移目录。
2. 更新导入路径与注册点。
3. 运行测试。
