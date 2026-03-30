# -*- coding: utf-8 -*-
"""Completion detection for persistent CLI processes.

Determines when the CLI has finished processing a user turn by inspecting
the stream-json output.

Detection strategies (in priority order):
    1. **JSON ``result`` event** — the CLI emits ``{"type": "result", ...}``
       at the end of each turn.  This is the most reliable signal.
    2. **Quiescence timeout** — if no new output arrives for *N* seconds
       after the last line, we consider the turn complete.  This is a
       fallback for providers that don't emit a ``result`` event.
"""

from __future__ import annotations

import enum
import json
from typing import Optional


class CompletionStatus(enum.Enum):
    """Status returned by ``CompletionDetector.check_line()``."""

    ONGOING = "ongoing"
    """The turn is still in progress."""

    DONE = "done"
    """A definitive completion signal was found (``result`` event)."""

    ERROR = "error"
    """An error event that terminates the turn."""


class CompletionDetector:
    """Stateful detector that inspects stream-json lines for turn boundaries.

    Args:
        quiescence_timeout: Seconds of silence before we declare "done".
            Used as a fallback when no ``result`` event is received.
    """

    def __init__(self, quiescence_timeout: float = 3.0):
        self.quiescence_timeout = quiescence_timeout
        self._session_id: Optional[str] = None

    @property
    def session_id(self) -> Optional[str]:
        """CLI session ID extracted from ``init`` or ``result`` events."""
        return self._session_id

    def check_line(self, raw_line: str) -> CompletionStatus:
        """Inspect a single JSON line and return its completion status.

        Also extracts and stores ``session_id`` from ``init`` / ``result``
        events for the caller to use (e.g. to persist to Redis).

        Args:
            raw_line: A single line of stream-json output (already stripped).

        Returns:
            ``CompletionStatus`` indicating whether the turn is done.
        """
        if not raw_line:
            return CompletionStatus.ONGOING

        try:
            data = json.loads(raw_line)
        except (json.JSONDecodeError, TypeError):
            return CompletionStatus.ONGOING

        event_type = data.get("type")

        # Extract session_id from init/result events
        if event_type in ("system", "result"):
            sid = data.get("session_id")
            if sid:
                self._session_id = sid

        if event_type == "result":
            return CompletionStatus.DONE

        if event_type == "error":
            return CompletionStatus.ERROR

        return CompletionStatus.ONGOING

    def reset(self) -> None:
        """Reset state for a new turn (keeps session_id)."""
        pass  # Currently stateless per-turn; placeholder for future use.
