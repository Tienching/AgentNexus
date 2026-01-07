# Spec: Message Filtering

## MODIFIED Requirements

### Requirement: Content Cleaning Filter

系统应在处理用户输入前，过滤掉前端发送的系统事件消息。

#### Scenario: Filter enter_chat event

**Given** 前端发送了一条内容为 `{"event_type": "enter_chat"}` 的消息
**When** 系统调用 `_clean_content` 方法处理该消息
**Then** 方法应返回空字符串，该消息不会被传递给 CCR 处理

#### Scenario: Normal message passes through

**Given** 用户发送了一条正常的聊天消息 "你好"
**When** 系统调用 `_clean_content` 方法处理该消息
**Then** 方法应返回原始消息内容 "你好"

#### Scenario: Mixed content filtering

**Given** 用户消息中包含了 `{"event_type": "enter_chat"}` 以及正常文本 "你好"
**When** 系统调用 `_clean_content` 方法处理该消息
**Then** 方法应移除 `{"event_type": "enter_chat"}` 部分并返回 "你好"
