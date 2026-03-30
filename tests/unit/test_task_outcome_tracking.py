# -*- coding: utf-8 -*-
"""Tests for task outcome tracking.

Ported from mission-control commit 6cf4256.

Covers:
- Task model new fields (outcome, resolution, feedback_rating, feedback_notes)
- Task.from_redis_hash round-trip for outcome fields
- PATCH /api/nexus/tasks/{task_id}/outcome endpoint
- GET /api/nexus/tasks/outcomes analytics endpoint
- UpdateTaskOutcomeRequest validation (valid/invalid outcomes, rating bounds)
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from src.runtime.models.task_models import Task, TaskStatus, TaskPriority
from src.server.routers.nexus_models import (
    UpdateTaskOutcomeRequest,
    TaskOutcomesResponse,
    TaskOutcomeSummary,
    OutcomeBuckets,
    task_to_item,
)


# ---------------------------------------------------------------------------
# Task model — field presence and round-trip
# ---------------------------------------------------------------------------

class TestTaskOutcomeFields:
    """New outcome fields on Task model."""

    def test_outcome_defaults_to_none(self):
        task = Task(description="test")
        assert task.outcome is None

    def test_resolution_defaults_to_none(self):
        task = Task(description="test")
        assert task.resolution is None

    def test_feedback_rating_defaults_to_none(self):
        task = Task(description="test")
        assert task.feedback_rating is None

    def test_feedback_notes_defaults_to_none(self):
        task = Task(description="test")
        assert task.feedback_notes is None

    def test_outcome_can_be_set(self):
        task = Task(description="test", outcome="success")
        assert task.outcome == "success"

    def test_feedback_rating_can_be_set(self):
        task = Task(description="test", feedback_rating=4)
        assert task.feedback_rating == 4


class TestTaskRedisRoundTrip:
    """to_redis_hash / from_redis_hash preserves outcome fields."""

    def test_outcome_survives_redis_roundtrip(self):
        task = Task(description="done", outcome="success", resolution="Fixed the bug")
        h = task.to_redis_hash()
        restored = Task.from_redis_hash(h)
        assert restored.outcome == "success"
        assert restored.resolution == "Fixed the bug"

    def test_feedback_rating_survives_redis_roundtrip(self):
        task = Task(description="done", feedback_rating=5, feedback_notes="Great!")
        h = task.to_redis_hash()
        restored = Task.from_redis_hash(h)
        assert restored.feedback_rating == 5
        assert restored.feedback_notes == "Great!"

    def test_outcome_not_in_hash_when_none(self):
        task = Task(description="test")
        h = task.to_redis_hash()
        assert "outcome" not in h

    def test_feedback_rating_not_in_hash_when_none(self):
        task = Task(description="test")
        h = task.to_redis_hash()
        assert "feedback_rating" not in h

    def test_feedback_rating_parsed_as_int(self):
        task = Task(description="test")
        h = task.to_redis_hash()
        h["feedback_rating"] = "3"
        restored = Task.from_redis_hash(h)
        assert restored.feedback_rating == 3
        assert isinstance(restored.feedback_rating, int)


# ---------------------------------------------------------------------------
# UpdateTaskOutcomeRequest validation
# ---------------------------------------------------------------------------

class TestUpdateTaskOutcomeRequest:
    """Request model validation."""

    def test_valid_success_outcome(self):
        req = UpdateTaskOutcomeRequest(outcome="success")
        assert req.outcome == "success"

    def test_valid_failed_outcome(self):
        req = UpdateTaskOutcomeRequest(outcome="failed")
        assert req.outcome == "failed"

    def test_valid_partial_outcome(self):
        req = UpdateTaskOutcomeRequest(outcome="partial")
        assert req.outcome == "partial"

    def test_valid_abandoned_outcome(self):
        req = UpdateTaskOutcomeRequest(outcome="abandoned")
        assert req.outcome == "abandoned"

    def test_feedback_rating_min_1(self):
        req = UpdateTaskOutcomeRequest(outcome="success", feedback_rating=1)
        assert req.feedback_rating == 1

    def test_feedback_rating_max_5(self):
        req = UpdateTaskOutcomeRequest(outcome="success", feedback_rating=5)
        assert req.feedback_rating == 5

    def test_feedback_rating_below_1_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            UpdateTaskOutcomeRequest(outcome="success", feedback_rating=0)

    def test_feedback_rating_above_5_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            UpdateTaskOutcomeRequest(outcome="success", feedback_rating=6)

    def test_optional_fields_default_none(self):
        req = UpdateTaskOutcomeRequest(outcome="success")
        assert req.resolution is None
        assert req.feedback_rating is None
        assert req.feedback_notes is None


# ---------------------------------------------------------------------------
# task_to_item includes outcome fields
# ---------------------------------------------------------------------------

class TestTaskToItemOutcomeFields:
    """task_to_item propagates outcome fields to TaskItem."""

    def test_outcome_propagated(self):
        task = Task(description="test", status=TaskStatus.DONE, outcome="success")
        item = task_to_item(task)
        assert item.outcome == "success"

    def test_resolution_propagated(self):
        task = Task(description="test", status=TaskStatus.DONE, resolution="All done")
        item = task_to_item(task)
        assert item.resolution == "All done"

    def test_feedback_rating_propagated(self):
        task = Task(description="test", status=TaskStatus.DONE, feedback_rating=4)
        item = task_to_item(task)
        assert item.feedback_rating == 4

    def test_feedback_notes_propagated(self):
        task = Task(description="test", status=TaskStatus.DONE, feedback_notes="Looks good")
        item = task_to_item(task)
        assert item.feedback_notes == "Looks good"

    def test_outcome_none_when_not_set(self):
        task = Task(description="test")
        item = task_to_item(task)
        assert item.outcome is None


# ---------------------------------------------------------------------------
# PATCH /api/nexus/tasks/{task_id}/outcome endpoint (unit, mocked queue)
# ---------------------------------------------------------------------------

class TestUpdateTaskOutcomeEndpoint:
    """Unit tests for the update_task_outcome route handler."""

    def _make_task(self, **kwargs) -> Task:
        defaults = dict(description="test task", status=TaskStatus.DONE)
        defaults.update(kwargs)
        return Task(**defaults)

    @pytest.mark.asyncio
    @patch("src.server.routers.nexus_tasks.get_task_queue")
    async def test_valid_outcome_persisted(self, mock_get_queue):
        from src.server.routers.nexus_tasks import update_task_outcome

        task = self._make_task()
        queue = MagicMock()
        queue.get_task.side_effect = [task, task]  # first fetch, then after update
        queue._task_key.return_value = "task:key"
        mock_get_queue.return_value = queue

        req = UpdateTaskOutcomeRequest(outcome="success", feedback_rating=5)
        result = await update_task_outcome(task.id, req, exec_user="testuser")

        queue._redis.hset.assert_called_once()
        hset_updates = queue._redis.hset.call_args[0][1]
        assert hset_updates["outcome"] == "success"
        assert hset_updates["feedback_rating"] == "5"

    @pytest.mark.asyncio
    @patch("src.server.routers.nexus_tasks.get_task_queue")
    async def test_invalid_outcome_raises_400(self, mock_get_queue):
        from src.server.routers.nexus_tasks import update_task_outcome
        from fastapi import HTTPException

        task = self._make_task()
        queue = MagicMock()
        queue.get_task.return_value = task
        mock_get_queue.return_value = queue

        req = UpdateTaskOutcomeRequest(outcome="success")
        req.outcome = "bogus"  # bypass pydantic to test route validation

        with pytest.raises(HTTPException) as exc_info:
            await update_task_outcome(task.id, req, exec_user="testuser")
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    @patch("src.server.routers.nexus_tasks.get_task_queue")
    async def test_task_not_found_raises_404(self, mock_get_queue):
        from src.server.routers.nexus_tasks import update_task_outcome
        from fastapi import HTTPException

        queue = MagicMock()
        queue.get_task.return_value = None
        mock_get_queue.return_value = queue

        req = UpdateTaskOutcomeRequest(outcome="success")
        with pytest.raises(HTTPException) as exc_info:
            await update_task_outcome("nonexistent", req, exec_user="testuser")
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    @patch("src.server.routers.nexus_tasks.get_task_queue")
    async def test_resolution_and_notes_persisted(self, mock_get_queue):
        from src.server.routers.nexus_tasks import update_task_outcome

        task = self._make_task()
        queue = MagicMock()
        queue.get_task.side_effect = [task, task]
        queue._task_key.return_value = "task:key"
        mock_get_queue.return_value = queue

        req = UpdateTaskOutcomeRequest(
            outcome="partial",
            resolution="Partially fixed",
            feedback_notes="Needs more work",
        )
        await update_task_outcome(task.id, req, exec_user="testuser")

        hset_updates = queue._redis.hset.call_args[0][1]
        assert hset_updates["resolution"] == "Partially fixed"
        assert hset_updates["feedback_notes"] == "Needs more work"


# ---------------------------------------------------------------------------
# GET /api/nexus/tasks/outcomes analytics endpoint (unit, mocked queue)
# ---------------------------------------------------------------------------

class TestGetTaskOutcomesEndpoint:
    """Unit tests for the get_task_outcomes analytics route."""

    def _make_done_task(self, outcome=None, provider="claude", priority=TaskPriority.THOUGHT, **kwargs) -> Task:
        return Task(
            description="done task",
            status=TaskStatus.DONE,
            outcome=outcome,
            provider=provider,
            priority=priority,
            **kwargs,
        )

    @pytest.mark.asyncio
    @patch("src.server.routers.nexus_tasks.get_task_queue")
    async def test_empty_returns_zeros(self, mock_get_queue):
        from src.server.routers.nexus_tasks import get_task_outcomes

        queue = MagicMock()
        queue._redis.smembers.return_value = set()
        queue._status_key.return_value = "done-key"
        mock_get_queue.return_value = queue

        result = await get_task_outcomes(timeframe="all", exec_user="testuser")
        assert isinstance(result, TaskOutcomesResponse)
        assert result.summary.total_done == 0
        assert result.summary.success_rate == 0.0

    @pytest.mark.asyncio
    @patch("src.server.routers.nexus_tasks.get_task_queue")
    async def test_success_tasks_counted(self, mock_get_queue):
        from src.server.routers.nexus_tasks import get_task_outcomes

        t1 = self._make_done_task(outcome="success")
        t2 = self._make_done_task(outcome="success")
        t3 = self._make_done_task(outcome="failed")

        task_map = {t1.id: t1, t2.id: t2, t3.id: t3}
        queue = MagicMock()
        queue._redis.smembers.return_value = set(task_map.keys())
        queue.get_task.side_effect = task_map.get
        queue._status_key.return_value = "done-key"
        mock_get_queue.return_value = queue

        result = await get_task_outcomes(timeframe="all", exec_user="testuser")
        assert result.summary.total_done == 3
        assert result.summary.by_outcome.success == 2
        assert result.summary.by_outcome.failed == 1
        assert result.summary.with_outcome == 3
        assert abs(result.summary.success_rate - 2 / 3) < 1e-9

    @pytest.mark.asyncio
    @patch("src.server.routers.nexus_tasks.get_task_queue")
    async def test_unknown_outcome_counted_in_unknown_bucket(self, mock_get_queue):
        from src.server.routers.nexus_tasks import get_task_outcomes

        t1 = self._make_done_task(outcome=None)
        queue = MagicMock()
        queue._redis.smembers.return_value = {t1.id}
        queue.get_task.side_effect = lambda tid: t1 if tid == t1.id else None
        queue._status_key.return_value = "done-key"
        mock_get_queue.return_value = queue

        result = await get_task_outcomes(timeframe="all", exec_user="testuser")
        assert result.summary.with_outcome == 0
        assert result.summary.by_outcome.unknown == 1

    @pytest.mark.asyncio
    @patch("src.server.routers.nexus_tasks.get_task_queue")
    async def test_by_provider_breakdown(self, mock_get_queue):
        from src.server.routers.nexus_tasks import get_task_outcomes

        t1 = self._make_done_task(outcome="success", provider="claude")
        t2 = self._make_done_task(outcome="failed", provider="gemini")

        task_map = {t1.id: t1, t2.id: t2}
        queue = MagicMock()
        queue._redis.smembers.return_value = set(task_map.keys())
        queue.get_task.side_effect = task_map.get
        queue._status_key.return_value = "done-key"
        mock_get_queue.return_value = queue

        result = await get_task_outcomes(timeframe="all", exec_user="testuser")
        assert "claude" in result.by_provider
        assert "gemini" in result.by_provider
        assert result.by_provider["claude"]["success"] == 1
        assert result.by_provider["gemini"]["failed"] == 1

    @pytest.mark.asyncio
    @patch("src.server.routers.nexus_tasks.get_task_queue")
    async def test_timeframe_all_includes_old_tasks(self, mock_get_queue):
        from src.server.routers.nexus_tasks import get_task_outcomes

        old_task = self._make_done_task(outcome="success")
        old_task.completed_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        old_task.created_at = datetime(2020, 1, 1, tzinfo=timezone.utc)

        queue = MagicMock()
        queue._redis.smembers.return_value = {old_task.id}
        queue.get_task.side_effect = lambda tid: old_task if tid == old_task.id else None
        queue._status_key.return_value = "done-key"
        mock_get_queue.return_value = queue

        result = await get_task_outcomes(timeframe="all", exec_user="testuser")
        assert result.summary.total_done == 1

    @pytest.mark.asyncio
    @patch("src.server.routers.nexus_tasks.get_task_queue")
    async def test_timeframe_day_excludes_old_tasks(self, mock_get_queue):
        from src.server.routers.nexus_tasks import get_task_outcomes

        old_task = self._make_done_task(outcome="success")
        old_task.completed_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        old_task.created_at = datetime(2020, 1, 1, tzinfo=timezone.utc)

        queue = MagicMock()
        queue._redis.smembers.return_value = {old_task.id}
        queue.get_task.side_effect = lambda tid: old_task if tid == old_task.id else None
        queue._status_key.return_value = "done-key"
        mock_get_queue.return_value = queue

        result = await get_task_outcomes(timeframe="day", exec_user="testuser")
        assert result.summary.total_done == 0

    @pytest.mark.asyncio
    @patch("src.server.routers.nexus_tasks.get_task_queue")
    async def test_all_outcome_types_counted(self, mock_get_queue):
        from src.server.routers.nexus_tasks import get_task_outcomes

        outcomes = ["success", "failed", "partial", "abandoned"]
        tasks = [self._make_done_task(outcome=o) for o in outcomes]
        task_map = {t.id: t for t in tasks}

        queue = MagicMock()
        queue._redis.smembers.return_value = set(task_map.keys())
        queue.get_task.side_effect = task_map.get
        queue._status_key.return_value = "done-key"
        mock_get_queue.return_value = queue

        result = await get_task_outcomes(timeframe="all", exec_user="testuser")
        assert result.summary.by_outcome.success == 1
        assert result.summary.by_outcome.failed == 1
        assert result.summary.by_outcome.partial == 1
        assert result.summary.by_outcome.abandoned == 1
        assert result.summary.with_outcome == 4

    @pytest.mark.asyncio
    @patch("src.server.routers.nexus_tasks.get_task_queue")
    async def test_common_errors_aggregated(self, mock_get_queue):
        from src.server.routers.nexus_tasks import get_task_outcomes

        tasks = [
            self._make_done_task(outcome="failed", error_message="timeout error"),
            self._make_done_task(outcome="failed", error_message="timeout error"),
            self._make_done_task(outcome="failed", error_message="oom killed"),
        ]
        task_map = {t.id: t for t in tasks}

        queue = MagicMock()
        queue._redis.smembers.return_value = set(task_map.keys())
        queue.get_task.side_effect = task_map.get
        queue._status_key.return_value = "done-key"
        mock_get_queue.return_value = queue

        result = await get_task_outcomes(timeframe="all", exec_user="testuser")
        assert len(result.common_errors) >= 1
        top_error = result.common_errors[0]
        assert top_error["error_message"] == "timeout error"
        assert top_error["count"] == 2

    @pytest.mark.asyncio
    @patch("src.server.routers.nexus_tasks.get_task_queue")
    async def test_record_count_matches_rows(self, mock_get_queue):
        from src.server.routers.nexus_tasks import get_task_outcomes

        tasks = [self._make_done_task(outcome="success") for _ in range(5)]
        task_map = {t.id: t for t in tasks}

        queue = MagicMock()
        queue._redis.smembers.return_value = set(task_map.keys())
        queue.get_task.side_effect = task_map.get
        queue._status_key.return_value = "done-key"
        mock_get_queue.return_value = queue

        result = await get_task_outcomes(timeframe="all", exec_user="testuser")
        assert result.record_count == 5
