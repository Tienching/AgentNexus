# Dify Chat Skill

这是一个专门用于调用Dify API进行对话查询的Claude Code技能，可以将您的curl命令封装成一个易于使用的skill。

## 文件结构

```
dify-chat/
├── SKILL.md          # Claude Code技能定义文件
├── dify_chat.py      # Python实现脚本
├── dify_query.sh     # Shell调用脚本
├── config.json       # 配置文件
└── README.md         # 说明文档
```

## 快速开始

### 1. 配置API信息

编辑 `config.json` 文件，设置正确的API配置：

```json
{
  "api_url": "http://api.dify.woa.com/v1/chat-messages",
  "api_key": "你的API密钥",
  "default_user": "你的用户名"
}
```

### 2. 使用方法

#### 通过Claude Code技能调用：
```
/skill dify-chat "bgp怎么配"
```

#### 直接通过Python脚本调用：
```bash
cd .claude/skills/dify-chat
python3 dify_chat.py "bgp怎么配"
```

#### 通过Shell脚本调用：
```bash
cd .claude/skills/dify-chat
./dify_query.sh "bgp怎么配"
```

## 功能特性

- ✅ **双重实现**: 支持Python urllib和curl两种调用方式
- ✅ **流式响应**: 处理Dify API的流式输出
- ✅ **配置灵活**: 通过配置文件自定义API设置
- ✅ **错误处理**: 完善的错误处理和备选方案
- ✅ **中文支持**: 完全支持中文查询和响应

## 技术实现

### API调用流程

1. **参数构建**: 构建符合Dify API规范的请求参数
2. **双重调用**: 优先使用Python urllib，失败时自动切换到curl
3. **流式处理**: 解析SSE格式的流式响应
4. **结果整合**: 合并所有响应片段返回完整回答

### 错误处理

- API密钥验证失败
- 网络连接问题
- 响应解析错误
- 超时处理

## 配置说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| api_url | Dify API端点 | http://api.dify.woa.com/v1/chat-messages |
| api_key | API认证密钥 | app-HgRTR9OjB |
| default_user | 默认用户标识 | louiszcwang |

## 使用示例

```bash
# 查询BGP配置
python3 dify_chat.py "bgp怎么配"

# 查询网络故障处理
python3 dify_chat.py "交换机端口故障如何排查"

# 查询VLAN配置
./dify_query.sh "VLAN配置的步骤是什么"
```

## 故障排除

### 1. API密钥无效
- 检查 `config.json` 中的 `api_key` 是否正确
- 确认API密钥是否有访问权限

### 2. 网络连接问题
- 检查网络连接是否正常
- 确认API端点是否可访问

### 3. 响应为空
- 检查查询内容是否符合API要求
- 确认用户标识是否有效

## 开发说明

这个skill将您提供的curl命令：
```bash
curl -X POST 'http://api.dify.woa.com/v1/chat-messages' \
--header 'Authorization: Bearer app-HgRTR9OjB' \
--header 'Content-Type: application/json' \
--data-raw '{ "inputs": {}, "query": "bgp怎么配", "response_mode": "streaming", "user": "louiszcwang" }'
```

封装成了可配置、可复用的Claude Code技能，支持更灵活的使用方式。