"""Context window management for mission executor.

Adapted from OpenFang's 4-layer context management:
1. Per-result truncation — cap tool results to prevent single-result overflow
2. Context guard — scan messages before each LLM call, compact if over threshold
3. Emergency truncation — aggressive drop when near context limit
4. Progressive recovery — staged approach to context reduction

Design decisions:
- Token estimation via char count (avoids tiktoken dependency)
- Conservative 3.5 chars/token ratio (safe for mixed English/CJK)
- Preserves system prompt + initial user message + recent messages always
"""

from __future__ import annotations

import json
from typing import Any


def estimate_tokens(text: str, chars_per_token: float = 3.5) -> int:
    """Estimate token count from text length.

    Uses a conservative chars-per-token ratio:
    - English prose: ~4.0 chars/token
    - Code: ~3.5 chars/token
    - CJK text: ~1.5-2.0 chars/token
    - Mixed content: ~3.5 chars/token (conservative default)

    Args:
        text: Input text to estimate tokens for.
        chars_per_token: Characters per token ratio.

    Returns:
        Estimated token count (always >= 0).
    """
    if not text:
        return 0
    return max(1, int(len(text) / chars_per_token))


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate total token count for a list of messages.

    Accounts for message overhead (~4 tokens per message for role/formatting).
    """
    total = 0
    for msg in messages:
        # Message overhead (role, delimiters)
        total += 4

        # Content tokens
        content = msg.get("content", "")
        if content:
            total += estimate_tokens(str(content))

        # Tool call tokens (in assistant messages)
        tool_calls = msg.get("tool_calls", [])
        if tool_calls:
            for tc in tool_calls:
                # Function name + arguments
                func = tc.get("function", {})
                total += estimate_tokens(func.get("name", ""))
                args = func.get("arguments", "")
                total += estimate_tokens(str(args))

    return total


def truncate_tool_result(
    result: str,
    max_tokens: int = 8000,
    chars_per_token: float = 3.5,
) -> str:
    """Truncate a tool result to fit within a token budget.

    Breaks at newline boundaries when possible for cleaner truncation.
    Preserves the beginning of the result (usually the most relevant).

    Args:
        result: Tool result string to potentially truncate.
        max_tokens: Maximum tokens allowed for this result.
        chars_per_token: Characters per token ratio.

    Returns:
        Original or truncated result string.
    """
    if not result:
        return result

    max_chars = int(max_tokens * chars_per_token)

    if len(result) <= max_chars:
        return result

    # Try to break at a newline boundary
    truncated = result[:max_chars]
    last_newline = truncated.rfind("\n")

    if last_newline > max_chars * 0.5:
        # Break at newline if it's in the latter half
        truncated = truncated[:last_newline]
    # else: break at max_chars (no good newline found)

    lines_dropped = result.count("\n") - truncated.count("\n")
    return (
        f"{truncated}\n\n... [truncated: ~{lines_dropped} lines dropped, "
        f"original ~{len(result)} chars]"
    )


def check_context_budget(
    messages: list[dict[str, Any]],
    max_tokens: int = 100_000,
    compact_threshold: float = 0.75,
    keep_recent: int = 6,
) -> list[dict[str, Any]]:
    """Check if messages exceed context budget and compact if needed.

    Layer 2 of 4-layer context management (adapted from OpenFang).
    If estimated tokens exceed compact_threshold * max_tokens, drops
    older messages while preserving system prompt, initial user message,
    and the most recent messages.

    Args:
        messages: Current message history.
        max_tokens: Total context window size in tokens.
        compact_threshold: Fraction of max_tokens that triggers compaction (0.0-1.0).
        keep_recent: Number of recent messages to always preserve.

    Returns:
        Potentially compacted message list.
    """
    if len(messages) <= keep_recent + 2:
        # Too few messages to compact
        return messages

    current_tokens = estimate_messages_tokens(messages)
    threshold = int(max_tokens * compact_threshold)

    if current_tokens <= threshold:
        return messages

    # Compact: keep system + first user + last N messages
    # Summarize the middle as a single "context" message
    return _compact_messages(messages, keep_recent, current_tokens, max_tokens)


def _compact_messages(
    messages: list[dict[str, Any]],
    keep_recent: int,
    current_tokens: int,
    max_tokens: int,
) -> list[dict[str, Any]]:
    """Compact messages by summarizing the middle portion.

    Strategy:
    - Keep messages[0] (system prompt) always
    - Keep messages[1] (initial user message) always
    - Summarize messages[2:-keep_recent] into a single context message
    - Keep messages[-keep_recent:] (recent messages) always
    """
    if len(messages) <= keep_recent + 2:
        return messages

    system_msg = messages[0]
    first_user_msg = messages[1]
    middle = messages[2:-keep_recent] if keep_recent > 0 else messages[2:]
    recent = messages[-keep_recent:] if keep_recent > 0 else []

    # Build summary of dropped middle messages
    summary_parts = []
    tool_calls_count = 0
    tool_results_count = 0
    assistant_responses = 0

    for msg in middle:
        role = msg.get("role", "")
        if role == "assistant":
            assistant_responses += 1
            tcs = msg.get("tool_calls", [])
            if tcs:
                tool_calls_count += len(tcs)
        elif role == "tool":
            tool_results_count += 1

    summary_parts.append(
        f"[Context compacted: {len(middle)} messages removed to fit context window. "
        f"Contained {assistant_responses} assistant responses, "
        f"{tool_calls_count} tool calls, {tool_results_count} tool results. "
        f"Tokens before: ~{current_tokens}, budget: {max_tokens}]"
    )

    # Extract any completed/failed status from middle for context preservation
    for msg in middle:
        content = str(msg.get("content", ""))
        if msg.get("role") == "assistant" and not msg.get("tool_calls"):
            # This was a final response from the assistant — keep a brief excerpt
            if len(content) > 200:
                summary_parts.append(f"Previous assistant note: {content[:200]}...")
            elif content.strip():
                summary_parts.append(f"Previous assistant note: {content}")

    context_summary = {
        "role": "user",
        "content": "\n".join(summary_parts),
    }

    return [system_msg, first_user_msg, context_summary] + recent


def emergency_truncate(
    messages: list[dict[str, Any]],
    max_tokens: int = 100_000,
    emergency_threshold: float = 0.90,
    keep_recent: int = 4,
) -> list[dict[str, Any]]:
    """Emergency truncation — last resort when near context limit.

    Layer 3 of 4-layer context management. More aggressive than
    check_context_budget: keeps fewer messages, no summary.

    Args:
        messages: Current message history.
        max_tokens: Total context window size in tokens.
        emergency_threshold: Fraction triggering emergency truncation.
        keep_recent: Minimum recent messages to keep (fewer than normal compact).

    Returns:
        Aggressively truncated message list.
    """
    current_tokens = estimate_messages_tokens(messages)
    threshold = int(max_tokens * emergency_threshold)

    if current_tokens <= threshold:
        return messages

    # Emergency: keep only system + first user + last N
    if len(messages) <= keep_recent + 2:
        return messages

    system_msg = messages[0]
    first_user_msg = messages[1]
    recent = messages[-keep_recent:]

    dropped = len(messages) - keep_recent - 2
    notice = {
        "role": "user",
        "content": (
            f"[EMERGENCY: Context window nearly full. "
            f"{dropped} messages dropped. "
            f"Focus on completing the current task efficiently.]"
        ),
    }

    return [system_msg, first_user_msg, notice] + recent
