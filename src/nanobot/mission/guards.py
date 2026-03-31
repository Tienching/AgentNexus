"""Guards for mission executor: loop detection, session repair, stability.

Adapted from OpenFang's agent hardening patterns:
- LoopGuard: SHA256-based tool call deduplication with ping-pong detection,
  outcome tracking, poll-tool relaxation, and escalation levels.
- SessionRepair: Message history validation, repair, and sanitization
  before LLM calls.
- STABILITY_GUIDELINES: Behavioral rules appended to system prompts.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Any


class LoopGuard:
    """Detect and prevent tool call loops.

    Tracks tool calls by hashing (tool_name, arguments) and detects:
    1. Repeated identical calls (warn at threshold, block at limit)
    2. Ping-pong patterns (A-B-A-B alternation)
    3. Total call budget exhaustion
    4. Repeated identical outcomes (same call producing same result)

    Poll-like tools (exec, shell, list_dir) receive relaxed thresholds
    since they are naturally called repeatedly.

    After multiple warnings are issued, subsequent warnings auto-escalate
    to blocks.

    Adapted from OpenFang's loop_guard.rs.
    """

    # Tools that are naturally called repeatedly (monitoring, polling).
    # These get relaxed warn/block thresholds.
    _POLL_TOOLS: set[str] = {
        "exec",
        "shell",
        "list_dir",
        "ssh_run",
        "ssh_shell",
        "ssh_server_run",
        "ssh_configure",
        "ping_ip",
    }

    # Number of identical outcomes before escalating to block.
    _OUTCOME_REPEAT_LIMIT: int = 3

    # After this many warnings, all subsequent warnings become blocks.
    _WARNING_ESCALATION_LIMIT: int = 3

    def __init__(
        self,
        warn_threshold: int = 3,
        block_threshold: int = 5,
        max_total_calls: int = 50,
    ):
        self.warn_threshold = warn_threshold
        self.block_threshold = block_threshold
        self.max_total_calls = max_total_calls

        self._call_hashes: list[str] = []
        self._hash_counts: Counter[str] = Counter()
        self._total_calls: int = 0

        # Outcome tracking: SHA256(tool|params|truncated_result) -> count
        self._outcome_counts: Counter[str] = Counter()

        # Escalation: number of warnings issued so far
        self._warnings_issued: int = 0

    def _make_hash(self, tool_name: str, arguments: dict[str, Any] | str) -> str:
        """Create a stable hash for a tool call."""
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except (json.JSONDecodeError, TypeError):
                arguments = {"_raw": arguments}

        # Sort keys for stable hashing
        canonical = json.dumps(
            {"tool": tool_name, "args": arguments},
            sort_keys=True,
            ensure_ascii=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    def _make_outcome_hash(
        self, tool_name: str, arguments: dict[str, Any] | str, result_str: str
    ) -> str:
        """Create a stable hash for a tool call + its result (outcome)."""
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except (json.JSONDecodeError, TypeError):
                arguments = {"_raw": arguments}

        # Truncate result to first 2000 chars to keep hashing fast and stable
        truncated_result = result_str[:2000] if result_str else ""

        canonical = json.dumps(
            {"tool": tool_name, "args": arguments, "result": truncated_result},
            sort_keys=True,
            ensure_ascii=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    def _get_thresholds(self, tool_name: str) -> tuple[int, int]:
        """Return (warn, block) thresholds for the given tool.

        Poll-like tools get relaxed thresholds.
        """
        if tool_name in self._POLL_TOOLS:
            # Relaxed thresholds for poll-like tools
            return (max(self.warn_threshold, 5), max(self.block_threshold, 8))
        return (self.warn_threshold, self.block_threshold)

    def check_call(self, tool_name: str, arguments: dict[str, Any] | str) -> str:
        """Check a tool call for loop patterns.

        Args:
            tool_name: Name of the tool being called.
            arguments: Tool call arguments (dict or JSON string).

        Returns:
            'ok': Call is fine, proceed normally.
            'warn': Possible loop detected, append warning to result.
            'block': Definite loop, block the call entirely.
        """
        self._total_calls += 1

        # Budget check
        if self._total_calls > self.max_total_calls:
            return "block"

        call_hash = self._make_hash(tool_name, arguments)
        self._call_hashes.append(call_hash)
        self._hash_counts[call_hash] += 1

        count = self._hash_counts[call_hash]
        warn_thresh, block_thresh = self._get_thresholds(tool_name)

        if count >= block_thresh:
            return "block"

        if count >= warn_thresh:
            return self._maybe_escalate("warn")

        # Check ping-pong pattern (A-B-A-B)
        if self._detect_ping_pong():
            return self._maybe_escalate("warn")

        return "ok"

    def record_outcome(
        self,
        tool_name: str,
        arguments: dict[str, Any] | str,
        result_str: str,
    ) -> str:
        """Record the outcome of a tool call and check for repeated outcomes.

        Should be called after a tool call completes with its result.

        Args:
            tool_name: Name of the tool that was called.
            arguments: Tool call arguments (dict or JSON string).
            result_str: The string result of the tool call.

        Returns:
            'ok': Outcome is fine.
            'warn': This exact outcome has been seen before.
            'block': Same call has produced the same result too many times.
        """
        outcome_hash = self._make_outcome_hash(tool_name, arguments, result_str)
        self._outcome_counts[outcome_hash] += 1

        count = self._outcome_counts[outcome_hash]

        if count >= self._OUTCOME_REPEAT_LIMIT:
            return "block"

        if count >= 2:
            return self._maybe_escalate("warn")

        return "ok"

    def _maybe_escalate(self, level: str) -> str:
        """Potentially escalate a warning to a block after repeated warnings.

        After ``_WARNING_ESCALATION_LIMIT`` warnings have been issued,
        all subsequent warnings auto-escalate to blocks.
        """
        if level == "warn":
            self._warnings_issued += 1
            if self._warnings_issued > self._WARNING_ESCALATION_LIMIT:
                return "block"
        return level

    def _detect_ping_pong(self) -> bool:
        """Detect alternating A-B-A-B pattern in recent calls."""
        hashes = self._call_hashes
        if len(hashes) < 6:
            return False

        # Check last 6 calls for A-B-A-B-A-B pattern
        recent = hashes[-6:]
        if (
            recent[0] == recent[2] == recent[4]
            and recent[1] == recent[3] == recent[5]
            and recent[0] != recent[1]
        ):
            return True

        return False

    def get_warning_message(self, tool_name: str, arguments: dict[str, Any] | str) -> str:
        """Get a human-readable warning about the detected loop."""
        call_hash = self._make_hash(tool_name, arguments)
        count = self._hash_counts.get(call_hash, 0)

        if self._total_calls > self.max_total_calls:
            return (
                f"LOOP GUARD: Total tool call budget exhausted "
                f"({self._total_calls}/{self.max_total_calls} calls). "
                f"Stop and summarize what you've accomplished."
            )

        if count >= self.block_threshold:
            return (
                f"LOOP GUARD: Blocked repeated call to '{tool_name}' "
                f"({count} identical calls). "
                f"You must try a completely different approach."
            )

        if self._detect_ping_pong():
            return (
                f"LOOP GUARD: Ping-pong pattern detected. "
                f"You're alternating between the same two tool calls. "
                f"Break the cycle — try a different strategy."
            )

        return (
            f"LOOP GUARD: '{tool_name}' called {count} times with same arguments. "
            f"Consider trying a different approach."
        )

    def reset(self) -> None:
        """Reset all guard state.

        Useful for testing and between retries where a fresh slate is needed.
        """
        self._call_hashes.clear()
        self._hash_counts.clear()
        self._total_calls = 0
        self._outcome_counts.clear()
        self._warnings_issued = 0

    @property
    def stats(self) -> dict[str, Any]:
        """Get guard statistics for debugging."""
        return {
            "total_calls": self._total_calls,
            "unique_calls": len(self._hash_counts),
            "max_repeat": max(self._hash_counts.values()) if self._hash_counts else 0,
            "ping_pong_detected": self._detect_ping_pong(),
            "warnings_issued": self._warnings_issued,
            "unique_outcomes": len(self._outcome_counts),
        }


class SessionRepair:
    """Validate and repair message history before LLM calls.

    Fixes common issues that can cause LLM API errors:
    1. Orphaned tool results (tool message with no matching tool_call_id)
    2. Unmatched tool_use (assistant requested tool but no result followed)
    3. Empty content messages
    4. Consecutive same-role messages (merge where possible)

    Also provides sanitization to strip potentially dangerous content:
    - Large base64 blobs
    - Oversized tool results
    - Prompt injection markers

    Adapted from OpenFang's session_repair.rs.
    """

    # Base64 blob pattern: matches long base64 strings (500+ chars)
    _BASE64_PATTERN = re.compile(
        r'(?<![A-Za-z0-9+/])'  # not preceded by base64 char
        r'[A-Za-z0-9+/]{500,}={0,2}'  # 500+ base64 chars with optional padding
        r'(?![A-Za-z0-9+/])',  # not followed by base64 char
    )

    # Known prompt injection markers to strip from tool results
    _INJECTION_MARKERS: list[str] = [
        "<|im_start|>",
        "<|im_end|>",
        "<|endoftext|>",
        "<|system|>",
        "<|user|>",
        "<|assistant|>",
    ]

    # Maximum length for individual tool result content
    _MAX_TOOL_RESULT_LEN: int = 10000

    @staticmethod
    def sanitize(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Sanitize message content to remove potentially dangerous or bloated data.

        Performs:
        1. Strip base64 blobs > 500 chars (replace with placeholder)
        2. Truncate individual tool results > 10000 chars
        3. Strip prompt injection markers from tool results

        Args:
            messages: List of chat messages to sanitize.

        Returns:
            Sanitized copy of the message list.
        """
        sanitized: list[dict[str, Any]] = []

        for msg in messages:
            msg_copy = dict(msg)
            content = msg_copy.get("content")
            role = msg_copy.get("role", "")

            if isinstance(content, str) and content:
                if role == "tool":
                    # 1. Truncate oversized tool results first (before other transforms)
                    if len(content) > SessionRepair._MAX_TOOL_RESULT_LEN:
                        content = (
                            content[: SessionRepair._MAX_TOOL_RESULT_LEN]
                            + "\n[truncated: content exceeded "
                            + f"{SessionRepair._MAX_TOOL_RESULT_LEN} char limit]"
                        )

                    # 2. Strip prompt injection markers from tool results
                    for marker in SessionRepair._INJECTION_MARKERS:
                        content = content.replace(marker, "")

                # 3. Strip large base64 blobs (all roles)
                def _replace_b64(match: re.Match) -> str:
                    blob = match.group(0)
                    return f"[base64 data: {len(blob)} chars]"

                content = SessionRepair._BASE64_PATTERN.sub(_replace_b64, content)

                msg_copy["content"] = content

            # Handle list-style content (e.g., vision/multimodal messages)
            if isinstance(content, list):
                sanitized_parts: list[Any] = []
                for part in content:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        part_copy = dict(part)
                        text = part_copy["text"]

                        def _replace_b64_part(match: re.Match) -> str:
                            blob = match.group(0)
                            return f"[base64 data: {len(blob)} chars]"

                        text = SessionRepair._BASE64_PATTERN.sub(
                            _replace_b64_part, text
                        )

                        if role == "tool":
                            for marker in SessionRepair._INJECTION_MARKERS:
                                text = text.replace(marker, "")

                        part_copy["text"] = text
                        sanitized_parts.append(part_copy)
                    else:
                        sanitized_parts.append(part)
                msg_copy["content"] = sanitized_parts

            sanitized.append(msg_copy)

        return sanitized

    @staticmethod
    def repair(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Validate and repair message history.

        Args:
            messages: List of chat messages to validate.

        Returns:
            Repaired message list (may be modified copy or original if clean).
        """
        if not messages:
            return messages

        # Collect all tool_call_ids from assistant messages
        expected_tool_ids: set[str] = set()
        for msg in messages:
            if msg.get("role") == "assistant":
                for tc in msg.get("tool_calls", []):
                    tc_id = tc.get("id") or tc.get("function", {}).get("id")
                    if tc_id:
                        expected_tool_ids.add(tc_id)

        # Collect all tool_call_ids that have results
        received_tool_ids: set[str] = set()
        for msg in messages:
            if msg.get("role") == "tool":
                tc_id = msg.get("tool_call_id")
                if tc_id:
                    received_tool_ids.add(tc_id)

        repaired: list[dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role", "")

            # Skip empty non-system messages
            if role != "system" and not msg.get("content") and not msg.get("tool_calls"):
                if role != "tool":  # tool messages can have empty content
                    continue

            # Check orphaned tool results
            if role == "tool":
                tc_id = msg.get("tool_call_id")
                if tc_id and tc_id not in expected_tool_ids:
                    # Orphaned tool result -- skip it
                    continue

            repaired.append(msg)

        # Check for unmatched tool_use (assistant called tools but no results)
        # Insert synthetic error results
        unmatched = expected_tool_ids - received_tool_ids
        if unmatched:
            # Find the last assistant message with tool_calls and add error results after it
            insert_idx = len(repaired)
            for i in range(len(repaired) - 1, -1, -1):
                if repaired[i].get("role") == "assistant" and repaired[i].get("tool_calls"):
                    insert_idx = i + 1
                    break

            for tc_id in unmatched:
                # Find the tool name for this ID
                tool_name = "unknown"
                for msg in messages:
                    if msg.get("role") == "assistant":
                        for tc in msg.get("tool_calls", []):
                            found_id = tc.get("id") or tc.get("function", {}).get("id")
                            if found_id == tc_id:
                                tool_name = tc.get("function", {}).get("name", "unknown")
                                break

                synthetic_result = {
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "name": tool_name,
                    "content": "[Error: Tool result was lost during context management. "
                    "Please retry or try a different approach.]",
                }
                repaired.insert(insert_idx, synthetic_result)
                insert_idx += 1

        # Sanitize all messages before returning
        repaired = SessionRepair.sanitize(repaired)

        return repaired


# Stability guidelines appended to every mission agent system prompt.
# These behavioral rules prevent common failure patterns in long-running agents.
# Adapted from OpenFang's stability guidelines pattern.
STABILITY_GUIDELINES = (
    "\n## Operational Guidelines\n"
    "- Do NOT call the same tool with identical arguments more than twice.\n"
    "- If a tool returns an error, try a DIFFERENT approach rather than retrying the same call.\n"
    "- If you feel stuck in a loop, STOP and summarize what you've tried so far.\n"
    "- Always read files before writing to avoid overwriting important content.\n"
    "- When your task is complete, provide a clear summary and STOP — do not keep working.\n"
    "- Do not attempt to verify your own work more than once.\n"
    "- Prefer small, incremental changes over large rewrites.\n"
    "- If you encounter an unexpected state, describe it rather than trying to force-fix it.\n"
    "- If you see '[truncated:' in a tool result, do NOT retry the same call hoping for more content.\n"
    "- When reading large files, use offset/limit parameters to read specific sections.\n"
    "- If a task requires more than 15 tool calls, pause and reassess your approach.\n"
)
