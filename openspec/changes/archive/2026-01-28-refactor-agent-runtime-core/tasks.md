## Phase 1: Core 引入
- [x] 1.1 创建 `src/agent_runtime/` 包结构
- [x] 1.2 定义统一事件模型 (`events/`)
- [x] 1.3 迁移 provider registry 到 `agent_runtime/providers/`
- [x] 1.4 实现 claude provider events 转换
- [x] 1.5 实现 gemini provider events 转换
- [x] 1.6 验证现有测试通过

## Phase 2: Protocol 解耦
- [x] 2.1 重构 AGUI adapter 消费统一 events
- [x] 2.2 重构 wecom（原 legacy）adapter 消费统一 events
- [x] 2.3 移除 adapter 对 provider raw event 的直接依赖
- [x] 2.4 迁移 protocols 到 `agent_runtime/protocols/`
- [x] 2.5 验证 Nexus UI / 企微对接正常

## Phase 3: Channel 插件
- [x] 3.1 设计 channel 插件接口 (`channels/base.py`)
- [x] 3.2 实现 WeWork channel (`channels/wecom/`)
- [x] 3.3 实现 channel routing 规则 (`routing/`)
- [x] 3.4 集成 channel 到 runtime
- [x] 3.5 验证企微消息收发

## Phase 4: CLI 安装器
- [x] 4.1 创建 `vhsdk` CLI 入口 (`plugins/cli.py`)
- [x] 4.2 实现 `vhsdk install channel <name>` 命令
- [x] 4.3 实现 `vhsdk install provider <name>` 命令
- [x] 4.4 配置模板生成逻辑
- [x] 4.5 添加 console_scripts 入口到 pyproject.toml
- [x] 4.6 验证安装流程

## Phase 5: 收尾与文档
- [x] 5.1 清理旧代码（保留兼容层）
- [x] 5.2 更新 pyproject.toml 依赖结构
- [x] 5.3 `openspec validate refactor-agent-runtime-core --strict`
- [x] 5.4 全量回归测试通过
