# -*- coding: utf-8 -*-
"""Unit tests for classify_task_model()

Ported from mission-control's task-dispatch.ts classifyTaskModel logic.
Verifies the three-tier model selection (opus / haiku / None) against
task descriptions and priorities.
"""

import pytest
from unittest.mock import MagicMock
from typing import Optional

from src.server.services.task_execution_service import classify_task_model


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(description: str = "", priority: str = "thought", model: str = "") -> MagicMock:
    """Build a minimal Task-like mock for classify_task_model()."""
    task = MagicMock()
    task.description = description
    task.priority = priority
    task.model = model
    return task


# ---------------------------------------------------------------------------
# Explicit model override — must always be respected
# ---------------------------------------------------------------------------

class TestExplicitModelOverride:
    def test_explicit_model_bypasses_classification(self):
        task = _make_task(
            description="debug why the service is broken",
            priority="thought",
            model="glm-5v-turbo",
        )
        result = classify_task_model(task)
        assert result == "glm-5v-turbo", (
            "When task.model is set explicitly it must be returned unchanged"
        )

    def test_explicit_model_survives_high_priority(self):
        task = _make_task(
            description="investigate production incident",
            priority="project",
            model="claude-sonnet-4-5",
        )
        assert classify_task_model(task) == "claude-sonnet-4-5"

    def test_empty_model_falls_through_to_classification(self):
        task = _make_task(description="summarize the report", priority="thought", model="")
        result = classify_task_model(task)
        assert result == "claude-haiku-4-5-20251001"


# ---------------------------------------------------------------------------
# Complex signals → Opus
# ---------------------------------------------------------------------------

class TestComplexSignals:
    @pytest.mark.parametrize("description", [
        "debug why the login fails after deploy",
        "diagnose the network connectivity issue",
        "architect the new microservice system",
        "security audit for the payment module",
        "root cause analysis of the outage",
        "investigate the memory leak in the API",
        "incident response for the production failure",
        "the service is broken and not working",
        "refactor the authentication module",
        "database migration from SQLite to PostgreSQL",
        "performance optim for the query layer",
        "why is the build failing on CI",
    ])
    def test_complex_keyword_triggers_opus(self, description: str):
        task = _make_task(description=description, priority="thought")
        result = classify_task_model(task)
        assert result == "claude-opus-4-6", (
            f"Complex signal in {description!r} should select opus"
        )

    def test_project_priority_always_selects_opus(self):
        """project priority = top priority → complex model regardless of text."""
        task = _make_task(description="send a status update email", priority="project")
        result = classify_task_model(task)
        assert result == "claude-opus-4-6"

    def test_serious_priority_with_no_signals_returns_none(self):
        """serious priority with no keywords → let provider decide."""
        task = _make_task(description="write unit tests for the parser", priority="serious")
        result = classify_task_model(task)
        assert result is None


# ---------------------------------------------------------------------------
# Routine signals → Haiku
# ---------------------------------------------------------------------------

class TestRoutineSignals:
    @pytest.mark.parametrize("description", [
        "status check on the gateway",
        "health check the worker service",
        "fetch the latest metrics",
        "format the JSON output",
        "rename the config file",
        "move file from /tmp to /data",
        "read file contents and return them",
        "update readme with new instructions",
        "bump version to 1.2.3",
        "send message to the slack channel",
        "post to the webhook endpoint",
        "notify the team of the deploy",
        "summarize the meeting notes",
        "translate this paragraph to English",
        "quick review of the PR",
        "simple unit test for the helper",
        "routine maintenance task",
        "minor typo fix in the docs",
    ])
    def test_routine_keyword_with_thought_priority_selects_haiku(self, description: str):
        task = _make_task(description=description, priority="thought")
        result = classify_task_model(task)
        assert result == "claude-haiku-4-5-20251001", (
            f"Routine signal in {description!r} (thought priority) should select haiku"
        )

    def test_routine_keyword_with_generated_priority_selects_haiku(self):
        task = _make_task(description="ping the healthcheck endpoint", priority="generated")
        result = classify_task_model(task)
        assert result == "claude-haiku-4-5-20251001"

    def test_routine_keyword_does_not_override_serious_priority(self):
        """serious priority + routine text → no auto-downgrade to haiku."""
        task = _make_task(description="summarize the meeting notes", priority="serious")
        result = classify_task_model(task)
        assert result is None, (
            "Routine keyword must NOT override serious priority — return None"
        )

    def test_routine_keyword_does_not_override_project_priority(self):
        """project priority always → opus, even with routine text."""
        task = _make_task(description="send message to CEO", priority="project")
        result = classify_task_model(task)
        assert result == "claude-opus-4-6"


# ---------------------------------------------------------------------------
# Default / no signal → None
# ---------------------------------------------------------------------------

class TestDefaultBehavior:
    @pytest.mark.parametrize("description,priority", [
        ("write a unit test for the parser module", "thought"),
        ("implement the new dashboard feature", "serious"),
        ("add logging to the background worker", "thought"),
        ("create a new API endpoint for users", "serious"),
        ("", "thought"),
        ("no recognizable keyword here", "thought"),
    ])
    def test_no_signal_returns_none(self, description: str, priority: str):
        task = _make_task(description=description, priority=priority)
        result = classify_task_model(task)
        assert result is None, (
            f"description={description!r}, priority={priority!r} "
            "has no strong signals and should return None"
        )

    def test_none_priority_field_does_not_crash(self):
        task = _make_task(description="investigate the crash", priority=None)
        task.priority = None
        result = classify_task_model(task)
        # complex signal → opus even with None priority
        assert result == "claude-opus-4-6"

    def test_none_description_does_not_crash(self):
        task = _make_task(priority="thought")
        task.description = None
        result = classify_task_model(task)
        assert result is None


# ---------------------------------------------------------------------------
# Edge cases: signal precedence
# ---------------------------------------------------------------------------

class TestSignalPrecedence:
    def test_complex_signal_beats_routine_signal(self):
        """Both complex and routine keywords present → complex wins (opus)."""
        task = _make_task(
            description="debug the status check endpoint quick",
            priority="thought",
        )
        result = classify_task_model(task)
        assert result == "claude-opus-4-6"

    def test_case_insensitive_matching(self):
        """Keywords should be matched case-insensitively."""
        task = _make_task(description="DEBUG the server crash", priority="thought")
        result = classify_task_model(task)
        assert result == "claude-opus-4-6"

    def test_partial_keyword_match(self):
        """'summarize' contains 'summarize' → routine match."""
        task = _make_task(description="summarize the weekly report", priority="thought")
        assert classify_task_model(task) == "claude-haiku-4-5-20251001"
