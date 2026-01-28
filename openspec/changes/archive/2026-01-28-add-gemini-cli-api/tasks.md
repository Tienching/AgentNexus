## 1. Implementation
- [x] 1.1 新增 `gemini_cli_api` 模块与执行器，支持 Gemini CLI stream-json 调用与逐行解析
- [x] 1.2 实现 Gemini stream-json -> AGUI 事件适配器（与现有 AGUI 语义一致）
- [x] 1.3 统一入口根据 `provider=gemini` 路由到 Gemini 执行链路（默认 Claude）
- [x] 1.4 增加解析与事件映射的最小化测试/示例验证
- [x] 1.5 验证 AGUI SSE 回放与归档链路兼容（手动或自动）
