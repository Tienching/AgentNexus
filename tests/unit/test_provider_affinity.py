# -*- coding: utf-8 -*-
"""Tests for provider affinity scoring.

Ported from mission-control autoRouteInboxTasks / scoreAgentForTask
(commit 1acbf8e).

Covers:
- score_provider_for_task(): known provider, unknown provider, affinity hits
- select_provider_for_task(): empty list, single provider, best-match, ties
- create_task endpoint: auto-select path, explicit provider path, fallback
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from src.server.services.task_execution_service import (
    score_provider_for_task,
    select_provider_for_task,
)


# ---------------------------------------------------------------------------
# score_provider_for_task()
# ---------------------------------------------------------------------------

class TestScoreProviderForTask:
    def test_unknown_provider_returns_zero(self):
        assert score_provider_for_task("openai", "build an API") == 0

    def test_empty_provider_returns_zero(self):
        assert score_provider_for_task("", "anything") == 0

    def test_minimum_score_is_1_for_known_provider(self):
        # No keywords match → still gets 1 (fallback)
        score = score_provider_for_task("claude", "xyz123 totally irrelevant text")
        assert score == 1

    def test_claude_scores_high_for_research(self):
        score = score_provider_for_task("claude", "research and investigate the security audit")
        assert score > 1  # multiple keyword hits

    def test_codex_scores_high_for_code_tasks(self):
        score = score_provider_for_task("codex", "implement unit test for the api endpoint function")
        assert score > 1

    def test_codebuddy_scores_high_for_routine(self):
        score = score_provider_for_task("codebuddy", "quick rename move file update readme")
        assert score > 1

    def test_score_is_additive_per_keyword(self):
        # "research" and "investigate" both in affinity for claude
        score_one = score_provider_for_task("claude", "research the topic")
        score_two = score_provider_for_task("claude", "research and investigate the topic")
        assert score_two > score_one

    def test_task_text_case_insensitive(self):
        lower = score_provider_for_task("claude", "research the topic")
        upper = score_provider_for_task("claude", "RESEARCH THE TOPIC")
        # score_provider_for_task expects already-lowercased text; upper won't match
        assert lower >= 1
        # upper-case won't match lowercase keywords — that's expected behaviour
        assert upper == 1  # minimum fallback

    def test_all_registered_providers_return_nonzero(self):
        """Every provider in the affinity table returns ≥ 1 for any text."""
        from src.server.services.task_execution_service import _PROVIDER_AFFINITY
        for provider in _PROVIDER_AFFINITY:
            assert score_provider_for_task(provider, "xyz") >= 1


# ---------------------------------------------------------------------------
# select_provider_for_task()
# ---------------------------------------------------------------------------

class TestSelectProviderForTask:
    def test_empty_providers_returns_none(self):
        assert select_provider_for_task("build an API", []) is None

    def test_single_provider_always_selected(self):
        result = select_provider_for_task("xyz", ["claude"])
        assert result == "claude"

    def test_selects_best_matching_provider(self):
        # Security audit → claude
        result = select_provider_for_task(
            "security audit and investigate the incident",
            ["claude", "codebuddy", "codex"],
        )
        assert result == "claude"

    def test_selects_codex_for_code_tasks(self):
        result = select_provider_for_task(
            "implement unit test for api endpoint and fix bug",
            ["claude", "codex", "codebuddy", "hermes"],
        )
        # codex has 'implement', 'unit test', 'api', 'endpoint', 'fix', 'bug'
        assert result == "codex"

    def test_selects_codebuddy_for_routine(self):
        result = select_provider_for_task(
            "quick rename move file",
            ["claude", "codex", "codebuddy"],
        )
        assert result == "codebuddy"

    def test_tie_broken_by_original_order(self):
        """When scores are equal, first provider in list wins."""
        # Use a text with no affinity keywords — all providers score 1
        result = select_provider_for_task(
            "do the task xyz",
            ["codex", "claude"],
        )
        # Both will score 1 (minimum); codex is first
        assert result == "codex"

    def test_unknown_providers_not_scored(self):
        """Providers not in the affinity table score 0 and lose to known ones."""
        result = select_provider_for_task(
            "research and analyze",
            ["openai", "claude"],
        )
        assert result == "claude"

    def test_returns_string_not_tuple(self):
        result = select_provider_for_task("build something", ["claude"])
        assert isinstance(result, str)

    def test_task_text_lowercased_internally(self):
        """select_provider_for_task handles upper-case input correctly."""
        result_lower = select_provider_for_task("research investigate", ["claude", "codebuddy"])
        result_upper = select_provider_for_task("RESEARCH INVESTIGATE", ["claude", "codebuddy"])
        # Both should pick claude (lower-cased internally)
        assert result_lower == "claude"
        assert result_upper == "claude"


# ---------------------------------------------------------------------------
# create_task route — auto-selection integration
# ---------------------------------------------------------------------------

class TestCreateTaskProviderAutoSelect:
    def _make_request(self, provider=None, desc="build an api endpoint"):
        req = MagicMock()
        req.description = desc
        req.provider = provider
        req.alias = None
        req.project_name = None
        req.project_id = None
        req.workspace = None
        req.llm_model = None
        req.source_session_id = None
        req.exec_user = None
        req.depends_on = []
        req.loop_enabled = False
        req.loop_max_iterations = 1
        req.loop_keywords = []
        return req

    def _make_queue(self):
        queue = MagicMock()
        task = MagicMock()
        task.id = "t1"
        task.description = "mock task description"
        task.status = "todo"
        task.priority = "thought"
        task.project_id = None
        task.project_name = None
        task.workspace = None
        task.provider = "codex"
        task.alias = "codex"
        task.created_at = None
        task.started_at = None
        task.completed_at = None
        task.error_message = None
        task.attempt_count = 0
        task.exec_user = "ubuntu"
        task.session_id = "task_t1"
        task.depends_on = []
        task.loop_enabled = False
        task.loop_iteration = 0
        task.loop_max_iterations = 1
        task.loop_keywords = []
        task.loop_keyword_found = False
        task.outcome = None
        task.resolution = None
        task.feedback_rating = None
        task.feedback_notes = None
        queue.add_task.return_value = task
        return queue

    @pytest.mark.asyncio
    async def test_explicit_provider_is_respected(self):
        """When caller specifies provider, affinity scoring is skipped."""
        from src.server.routers.nexus_tasks import create_task
        queue = self._make_queue()
        with patch("src.server.routers.nexus_tasks.get_task_queue", return_value=queue), \
             patch("src.server.routers.nexus_tasks.get_provider_registry") as mock_reg:
            mock_reg.return_value.list_providers.return_value = ["claude", "codex", "codebuddy"]
            await create_task(self._make_request(provider="claude"))
        # add_task should have been called with provider="claude"
        call_kwargs = queue.add_task.call_args
        assert call_kwargs.kwargs.get("provider") == "claude" or \
               (call_kwargs.args and "claude" in str(call_kwargs))

    @pytest.mark.asyncio
    async def test_auto_select_picks_affinity_provider(self):
        """No explicit provider → auto-selection chooses best fit."""
        from src.server.routers.nexus_tasks import create_task
        queue = self._make_queue()
        # codex-affinity task: implement unit test for api endpoint
        req = self._make_request(provider=None, desc="implement unit test for api endpoint function")
        with patch("src.server.routers.nexus_tasks.get_task_queue", return_value=queue), \
             patch("src.server.routers.nexus_tasks.get_provider_registry") as mock_reg:
            mock_reg.return_value.list_providers.return_value = ["claude", "codex", "codebuddy"]
            await create_task(req)
        call_kwargs = queue.add_task.call_args.kwargs
        assert call_kwargs["provider"] == "codex"

    @pytest.mark.asyncio
    async def test_auto_select_falls_back_to_default_on_empty_providers(self):
        """Empty provider list → falls back to default_provider from settings."""
        from src.server.routers.nexus_tasks import create_task
        queue = self._make_queue()
        req = self._make_request(provider=None)
        with patch("src.server.routers.nexus_tasks.get_task_queue", return_value=queue), \
             patch("src.server.routers.nexus_tasks.get_provider_registry") as mock_reg, \
             patch("src.server.routers.nexus_tasks.settings") as mock_settings:
            mock_reg.return_value.list_providers.return_value = []
            mock_settings.default_provider = "codebuddy"
            mock_settings.default_alias = ""
            mock_settings.default_exec_user = ""
            mock_settings.exec_user = "ubuntu"
            await create_task(req)
        call_kwargs = queue.add_task.call_args.kwargs
        assert call_kwargs["provider"] == "codebuddy"

    @pytest.mark.asyncio
    async def test_invalid_explicit_provider_raises_400(self):
        from fastapi import HTTPException
        from src.server.routers.nexus_tasks import create_task
        queue = self._make_queue()
        with patch("src.server.routers.nexus_tasks.get_task_queue", return_value=queue), \
             patch("src.server.routers.nexus_tasks.get_provider_registry") as mock_reg:
            mock_reg.return_value.list_providers.return_value = ["claude", "codex"]
            with pytest.raises(HTTPException) as exc:
                await create_task(self._make_request(provider="openai"))
            assert exc.value.status_code == 400
