# -*- coding: utf-8 -*-
"""Unit tests for MissionBridge service."""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path


class TestMissionBridgeSingleton:
    """Test singleton lifecycle."""

    def setup_method(self):
        """Reset singleton between tests."""
        from src.server.services.mission_bridge import MissionBridge
        MissionBridge.reset()

    def teardown_method(self):
        from src.server.services.mission_bridge import MissionBridge
        MissionBridge.reset()

    def test_singleton_returns_same_instance(self):
        from src.server.services.mission_bridge import MissionBridge
        a = MissionBridge.get_instance()
        b = MissionBridge.get_instance()
        assert a is b

    def test_reset_clears_singleton(self):
        from src.server.services.mission_bridge import MissionBridge
        a = MissionBridge.get_instance()
        MissionBridge.reset()
        b = MissionBridge.get_instance()
        assert a is not b

    def test_service_is_none_initially(self):
        from src.server.services.mission_bridge import MissionBridge
        bridge = MissionBridge.get_instance()
        assert bridge._service is None


class TestMissionBridgeMethods:
    """Test bridge methods with mocked MissionService."""

    def setup_method(self):
        from src.server.services.mission_bridge import MissionBridge
        MissionBridge.reset()

    def teardown_method(self):
        from src.server.services.mission_bridge import MissionBridge
        MissionBridge.reset()

    def _make_mock_mission(self, mission_id="msn-test1234", status="planned"):
        """Create a mock Mission object."""
        mock_token = MagicMock()
        mock_token.total_tokens = 100
        mock_token.prompt_tokens = 60
        mock_token.completion_tokens = 40
        mock_token.llm_iterations = 5
        mock_token.estimated_cost_usd = 0.001

        mock_mission = MagicMock()
        mock_mission.id = mission_id
        mock_mission.goal = "Test goal"
        mock_mission.mission_type = "general"
        mock_mission.status = status
        mock_mission.milestones = []
        mock_mission.total_tasks = 3
        mock_mission.completed_tasks = 0
        mock_mission.progress_pct = 0.0
        mock_mission.wall_clock_display = "0s"
        mock_mission.token_usage = mock_token
        mock_mission.error = None
        mock_mission.created_at_ms = 1000000
        mock_mission.updated_at_ms = 1000000
        mock_mission.log = ["[10:00:00] Mission planned"]
        return mock_mission

    @pytest.mark.asyncio
    async def test_plan_calls_service(self):
        from src.server.services.mission_bridge import MissionBridge

        bridge = MissionBridge.get_instance()
        mock_mission = self._make_mock_mission()

        mock_service = MagicMock()
        mock_service.plan_mission = AsyncMock(return_value=mock_mission)
        bridge._service = mock_service

        # Call without workspace to avoid store re-creation branch
        result = await bridge.plan("Test goal")
        assert result["id"] == "msn-test1234"
        assert result["status"] == "planned"
        assert result["goal"] == "Test goal"
        mock_service.plan_mission.assert_called_once()

    @pytest.mark.asyncio
    async def test_approve_delegates_to_service(self):
        from src.server.services.mission_bridge import MissionBridge

        bridge = MissionBridge.get_instance()
        mock_service = MagicMock()
        mock_service.confirm_mission = AsyncMock(return_value=True)
        bridge._service = mock_service

        result = await bridge.approve("msn-test1234")
        assert result is True
        mock_service.confirm_mission.assert_called_once_with("msn-test1234")

    @pytest.mark.asyncio
    async def test_cancel_delegates_to_service(self):
        from src.server.services.mission_bridge import MissionBridge

        bridge = MissionBridge.get_instance()
        mock_service = MagicMock()
        mock_service.cancel_mission = AsyncMock(return_value=True)
        bridge._service = mock_service

        result = await bridge.cancel("msn-test1234")
        assert result is True

    @pytest.mark.asyncio
    async def test_status_returns_formatted_text(self):
        from src.server.services.mission_bridge import MissionBridge

        bridge = MissionBridge.get_instance()
        mock_mission = self._make_mock_mission()

        mock_service = MagicMock()
        mock_service.get_mission.return_value = mock_mission
        mock_service.format_status.return_value = "## Mission: Test goal\n..."
        bridge._service = mock_service

        result = await bridge.status("msn-test1234")
        assert "Mission: Test goal" in result

    @pytest.mark.asyncio
    async def test_status_returns_none_for_missing(self):
        from src.server.services.mission_bridge import MissionBridge

        bridge = MissionBridge.get_instance()
        mock_service = MagicMock()
        mock_service.get_mission.return_value = None
        bridge._service = mock_service

        result = await bridge.status("msn-nonexist")
        assert result is None

    def test_get_log_with_tail(self):
        from src.server.services.mission_bridge import MissionBridge

        bridge = MissionBridge.get_instance()
        mock_mission = self._make_mock_mission()
        mock_mission.log = [f"[10:0{i}:00] Entry {i}" for i in range(10)]

        mock_service = MagicMock()
        mock_service.get_mission.return_value = mock_mission
        bridge._service = mock_service

        entries = bridge.get_log("msn-test1234", tail=3)
        assert len(entries) == 3
        assert "Entry 7" in entries[0]

    def test_get_log_missing_mission(self):
        from src.server.services.mission_bridge import MissionBridge

        bridge = MissionBridge.get_instance()
        mock_service = MagicMock()
        mock_service.get_mission.return_value = None
        bridge._service = mock_service

        entries = bridge.get_log("msn-nonexist")
        assert entries == []


class TestMissionToDict:
    """Test the _mission_to_dict serializer."""

    def test_basic_mission_serialization(self):
        from src.server.services.mission_bridge import MissionBridge

        # Create a simple mock with milestones and tasks
        mock_task_token = MagicMock()
        mock_task_token.total_tokens = 50
        mock_task_token.llm_iterations = 2

        mock_result = MagicMock()
        mock_result.status = "completed"
        mock_result.error = None
        mock_result.duration_seconds = 30.5
        mock_result.token_usage = mock_task_token

        mock_task = MagicMock()
        mock_task.id = "t-001"
        mock_task.title = "Write code"
        mock_task.description = "Write the implementation"
        mock_task.role = "coder"
        mock_task.status = "completed"
        mock_task.depends_on = []
        mock_task.result = mock_result

        mock_ms = MagicMock()
        mock_ms.id = "m-001"
        mock_ms.title = "Implementation"
        mock_ms.description = "Implement the feature"
        mock_ms.status = "completed"
        mock_ms.depends_on = []
        mock_ms.tasks = [mock_task]

        mock_token = MagicMock()
        mock_token.total_tokens = 100
        mock_token.prompt_tokens = 60
        mock_token.completion_tokens = 40
        mock_token.llm_iterations = 5
        mock_token.estimated_cost_usd = 0.001

        mock_mission = MagicMock()
        mock_mission.id = "msn-test1234"
        mock_mission.goal = "Build feature"
        mock_mission.mission_type = "feature"
        mock_mission.status = "completed"
        mock_mission.milestones = [mock_ms]
        mock_mission.total_tasks = 1
        mock_mission.completed_tasks = 1
        mock_mission.progress_pct = 100.0
        mock_mission.wall_clock_display = "30.5s"
        mock_mission.token_usage = mock_token
        mock_mission.error = None
        mock_mission.created_at_ms = 1000000
        mock_mission.updated_at_ms = 1000030

        result = MissionBridge._mission_to_dict(mock_mission)

        assert result["id"] == "msn-test1234"
        assert result["status"] == "completed"
        assert result["total_tasks"] == 1
        assert result["completed_tasks"] == 1
        assert len(result["milestones"]) == 1
        assert result["milestones"][0]["tasks"][0]["role"] == "coder"
        assert result["milestones"][0]["tasks"][0]["result"]["status"] == "completed"
