# Change: Add Gemini CLI API support via unified entry

## Why
当前仅支持 Claude Code 输出的 stream-json。需要新增 Gemini CLI 的 stream-json 解析与 AGUI 转换能力，并保持统一入口一致行为。

## What Changes
- 新增 `gemini_cli_api` 目录与执行器/解析器，支持 Gemini CLI `--output-format stream-json` 输出。
- 新增 Gemini stream-json -> AGUI 事件适配逻辑，行为与 `claude_code_api` 现有 AGUI 流完全一致。
- 统一入口根据请求标识选择 Claude 或 Gemini 后端执行与流式解析。
- 增加最小化测试/验证覆盖（解析与事件映射）。

## Impact
- Affected specs: `stream-adapters`
- Affected code:
  - `src/claude_code_api/...`（统一入口/路由/处理链路接入 Gemini）
  - `src/gemini_cli_api/...`（新增模块，结构对齐 `claude_code_api`）
