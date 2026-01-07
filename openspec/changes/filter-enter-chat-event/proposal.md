# Proposal: Filter enter_chat Event

## Summary

过滤前端进入聊天时发送的 `enter_chat` 事件消息，避免该事件被当作用户输入传递给 CCR 处理。

## Problem

前端应用在用户进入聊天界面时会自动发送一条格式为 `{"event_type": "enter_chat"}` 的消息。这条消息是前端的状态通知，不应该被当作用户的实际输入内容传递给 CCR 处理，否则会导致：

1. 不必要的 CCR 调用
2. 可能产生无意义的响应

## Solution

在现有的 `_clean_content` 方法中添加对 `enter_chat` 事件的过滤。该方法已经有 `triggers_to_remove` 列表机制，只需将 `enter_chat` 事件的 JSON 字符串添加到该列表即可。

## Scope

- **Affected Files**: `src/claude_code_api/ccr_service.py`
- **Affected Method**: `_clean_content()`
- **Change Type**: 配置项添加（在现有列表中添加新过滤项）

## Risk Assessment

- **Risk Level**: Low
- **Impact**: 仅影响 `enter_chat` 事件的过滤，不影响其他正常消息
- **Backward Compatibility**: 完全兼容，只是新增过滤规则
