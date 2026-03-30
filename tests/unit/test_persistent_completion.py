# -*- coding: utf-8 -*-
"""Unit tests for persistent process completion detection.

Tests the CompletionDetector that inspects stream-json lines from
persistent CLI processes to detect turn boundaries.
"""

import json

import pytest

from src.providers.persistent.completion_detector import (
    CompletionDetector,
    CompletionStatus,
)


class TestCompletionStatus:
    """Verify the CompletionStatus enum values."""

    def test_enum_values(self):
        assert CompletionStatus.ONGOING.value == "ongoing"
        assert CompletionStatus.DONE.value == "done"
        assert CompletionStatus.ERROR.value == "error"


class TestCompletionDetector:
    """Tests for CompletionDetector.check_line() and state management."""

    @pytest.fixture
    def detector(self):
        return CompletionDetector(quiescence_timeout=3.0)

    # ── Basic detection ──────────────────────────────────────────────

    def test_empty_line_returns_ongoing(self, detector):
        assert detector.check_line("") == CompletionStatus.ONGOING

    def test_non_json_returns_ongoing(self, detector):
        assert detector.check_line("not json at all") == CompletionStatus.ONGOING

    def test_invalid_json_returns_ongoing(self, detector):
        assert detector.check_line("{broken json") == CompletionStatus.ONGOING

    def test_assistant_event_returns_ongoing(self, detector):
        line = json.dumps({"type": "assistant", "message": {"content": "hello"}})
        assert detector.check_line(line) == CompletionStatus.ONGOING

    def test_content_block_event_returns_ongoing(self, detector):
        line = json.dumps({
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "hello"},
        })
        assert detector.check_line(line) == CompletionStatus.ONGOING

    def test_system_event_returns_ongoing(self, detector):
        line = json.dumps({"type": "system", "subtype": "init", "session_id": "abc"})
        assert detector.check_line(line) == CompletionStatus.ONGOING

    # ── Completion detection ─────────────────────────────────────────

    def test_result_event_returns_done(self, detector):
        line = json.dumps({
            "type": "result",
            "session_id": "sess-123",
            "cost_usd": 0.05,
        })
        assert detector.check_line(line) == CompletionStatus.DONE

    def test_error_event_returns_error(self, detector):
        line = json.dumps({
            "type": "error",
            "error": {"message": "Rate limit exceeded"},
        })
        assert detector.check_line(line) == CompletionStatus.ERROR

    # ── Session ID extraction ────────────────────────────────────────

    def test_session_id_extracted_from_init(self, detector):
        line = json.dumps({
            "type": "system",
            "subtype": "init",
            "session_id": "init-session-uuid",
        })
        detector.check_line(line)
        assert detector.session_id == "init-session-uuid"

    def test_session_id_extracted_from_result(self, detector):
        line = json.dumps({
            "type": "result",
            "session_id": "result-session-uuid",
        })
        detector.check_line(line)
        assert detector.session_id == "result-session-uuid"

    def test_session_id_not_extracted_from_assistant(self, detector):
        line = json.dumps({
            "type": "assistant",
            "session_id": "should-be-ignored",
        })
        detector.check_line(line)
        assert detector.session_id is None

    def test_session_id_updated_by_later_result(self, detector):
        # Init event sets session_id
        init_line = json.dumps({
            "type": "system",
            "subtype": "init",
            "session_id": "first-id",
        })
        detector.check_line(init_line)
        assert detector.session_id == "first-id"

        # Result event updates session_id
        result_line = json.dumps({
            "type": "result",
            "session_id": "second-id",
        })
        detector.check_line(result_line)
        assert detector.session_id == "second-id"

    def test_session_id_not_overwritten_by_missing(self, detector):
        """If a result event has no session_id, keep the previous one."""
        init_line = json.dumps({
            "type": "system",
            "subtype": "init",
            "session_id": "keep-this",
        })
        detector.check_line(init_line)

        result_line = json.dumps({"type": "result"})
        detector.check_line(result_line)
        assert detector.session_id == "keep-this"

    # ── Reset ────────────────────────────────────────────────────────

    def test_reset_preserves_session_id(self, detector):
        line = json.dumps({
            "type": "result",
            "session_id": "preserved",
        })
        detector.check_line(line)
        detector.reset()
        assert detector.session_id == "preserved"

    # ── Quiescence timeout ───────────────────────────────────────────

    def test_default_quiescence_timeout(self):
        d = CompletionDetector()
        assert d.quiescence_timeout == 3.0

    def test_custom_quiescence_timeout(self):
        d = CompletionDetector(quiescence_timeout=5.0)
        assert d.quiescence_timeout == 5.0

    def test_quiescence_timeout_can_be_updated(self, detector):
        detector.quiescence_timeout = 10.0
        assert detector.quiescence_timeout == 10.0

    # ── Edge cases ───────────────────────────────────────────────────

    def test_none_input(self, detector):
        """check_line should handle None gracefully (returns ONGOING)."""
        # The function checks `if not raw_line` which catches None
        assert detector.check_line(None) == CompletionStatus.ONGOING

    def test_json_with_unknown_type(self, detector):
        line = json.dumps({"type": "unknown_event_type", "data": "hello"})
        assert detector.check_line(line) == CompletionStatus.ONGOING

    def test_json_without_type_field(self, detector):
        line = json.dumps({"message": "no type field here"})
        assert detector.check_line(line) == CompletionStatus.ONGOING

    def test_sequential_events_in_typical_turn(self, detector):
        """Simulate a typical turn: system → assistant → content → result."""
        events = [
            ({"type": "system", "subtype": "init", "session_id": "s1"}, CompletionStatus.ONGOING),
            ({"type": "assistant", "message": {"role": "assistant"}}, CompletionStatus.ONGOING),
            ({"type": "content_block_start"}, CompletionStatus.ONGOING),
            ({"type": "content_block_delta", "delta": {"text": "Hello"}}, CompletionStatus.ONGOING),
            ({"type": "content_block_stop"}, CompletionStatus.ONGOING),
            ({"type": "result", "session_id": "s1", "cost_usd": 0.01}, CompletionStatus.DONE),
        ]
        for event_data, expected in events:
            line = json.dumps(event_data)
            status = detector.check_line(line)
            assert status == expected, f"Expected {expected} for {event_data['type']}, got {status}"
