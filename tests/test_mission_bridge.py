# -*- coding: utf-8 -*-
"""Unit tests for MissionBridge service."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.nanobot.mission.runner import MissionRunner
from src.nanobot.mission.store import MissionFileStore


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

    def test_service_cache_is_empty_initially(self):
        from src.server.services.mission_bridge import MissionBridge

        bridge = MissionBridge.get_instance()
        assert bridge._services == {}


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

    def _make_mock_service(self, workspace: Path):
        store = MissionFileStore(workspace / "missions.json")
        planner = MagicMock()
        planner.workspace = workspace
        executor = MagicMock()
        executor.workspace = workspace
        runner = MissionRunner(executor=executor, planner=planner, store=store)

        mock_service = MagicMock()
        mock_service.workspace = workspace
        mock_service.store = store
        mock_service.planner = planner
        mock_service.executor = executor
        mock_service.runner = runner
        mock_service.plan_mission = AsyncMock()
        mock_service.start_mission = AsyncMock()
        return mock_service

    def _set_default_service(self, bridge, service) -> None:
        bridge._services[bridge._default_workspace()] = service

    def _seed_non_default_mission_services(self, bridge, tmp_path, mission_id="msn-workspace"):
        default_workspace = bridge._default_workspace()
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        default_service = self._make_mock_service(default_workspace)
        default_service.get_mission = MagicMock(return_value=None)
        default_service.format_status = MagicMock(side_effect=AssertionError("default status used"))
        default_service.confirm_mission = AsyncMock(side_effect=AssertionError("default approve used"))
        default_service.cancel_mission = AsyncMock(side_effect=AssertionError("default cancel used"))
        default_service.pause_mission = AsyncMock(side_effect=AssertionError("default pause used"))
        default_service.resume_mission = AsyncMock(side_effect=AssertionError("default resume used"))

        workspace_service = self._make_mock_service(workspace)
        mission = self._make_mock_mission(mission_id=mission_id, status="running")
        mission.goal = "Workspace mission"
        mission.log = ["[10:00:00] Workspace log 1", "[10:01:00] Workspace log 2"]
        workspace_service.get_mission = MagicMock(return_value=mission)
        workspace_service.format_status = MagicMock(return_value="## Mission: Workspace mission\nStatus: running")
        workspace_service.confirm_mission = AsyncMock(return_value=True)
        workspace_service.cancel_mission = AsyncMock(return_value=True)
        workspace_service.pause_mission = AsyncMock(return_value=True)
        workspace_service.resume_mission = AsyncMock(return_value=True)

        bridge._services = {
            default_workspace: default_service,
            workspace: workspace_service,
        }
        return default_service, workspace_service, mission

    @pytest.mark.asyncio
    async def test_plan_calls_default_service(self):
        from src.server.services.mission_bridge import MissionBridge

        bridge = MissionBridge.get_instance()
        mock_mission = self._make_mock_mission()

        mock_service = MagicMock()
        mock_service.plan_mission = AsyncMock(return_value=mock_mission)
        self._set_default_service(bridge, mock_service)

        result = await bridge.plan("Test goal")
        assert result["id"] == "msn-test1234"
        assert result["status"] == "planned"
        assert result["goal"] == "Test goal"
        mock_service.plan_mission.assert_awaited_once_with(goal="Test goal", context="")

    def test_get_service_reuses_cached_service_for_same_workspace(self, tmp_path):
        from src.server.services.mission_bridge import MissionBridge

        bridge = MissionBridge.get_instance()
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        bridge._create_service = MagicMock(side_effect=self._make_mock_service)

        first = bridge._get_service(str(workspace))
        second = bridge._get_service(str(workspace))

        assert first is second
        bridge._create_service.assert_called_once_with(workspace)

    def test_get_service_isolates_different_workspaces(self, tmp_path):
        from src.server.services.mission_bridge import MissionBridge

        bridge = MissionBridge.get_instance()
        workspace_a = tmp_path / "workspace-a"
        workspace_b = tmp_path / "workspace-b"
        workspace_a.mkdir()
        workspace_b.mkdir()

        bridge._create_service = MagicMock(side_effect=self._make_mock_service)

        service_a = bridge._get_service(str(workspace_a))
        service_b = bridge._get_service(str(workspace_b))
        service_a_again = bridge._get_service(str(workspace_a))

        assert service_a is service_a_again
        assert service_a is not service_b
        assert service_a.workspace == workspace_a
        assert service_b.workspace == workspace_b
        assert service_a.store.store_path == workspace_a / "missions.json"
        assert service_b.store.store_path == workspace_b / "missions.json"
        assert service_a.planner.workspace == workspace_a
        assert service_b.planner.workspace == workspace_b
        assert service_a.executor.workspace == workspace_a
        assert service_b.executor.workspace == workspace_b
        assert service_a.runner.store is service_a.store
        assert service_b.runner.store is service_b.store
        assert service_a.runner.planner is service_a.planner
        assert service_b.runner.planner is service_b.planner
        assert service_a.runner.executor is service_a.executor
        assert service_b.runner.executor is service_b.executor

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("bridge_method", "service_method", "default_status", "workspace_status"),
        [
            ("plan", "plan_mission", "planned", "planned"),
            ("start", "start_mission", "running", "running"),
        ],
    )
    async def test_workspace_scoped_methods_delegate_without_cross_workspace_bleed(
        self,
        tmp_path,
        bridge_method,
        service_method,
        default_status,
        workspace_status,
    ):
        from src.server.services.mission_bridge import MissionBridge

        bridge = MissionBridge.get_instance()
        default_workspace = bridge._default_workspace()
        requested_workspace = tmp_path / "requested"
        requested_workspace.mkdir()

        default_service = self._make_mock_service(default_workspace)
        requested_service = self._make_mock_service(requested_workspace)
        default_mission = self._make_mock_mission("msn-default", status=default_status)
        requested_mission = self._make_mock_mission("msn-requested", status=workspace_status)

        getattr(default_service, service_method).return_value = default_mission
        getattr(requested_service, service_method).return_value = requested_mission
        bridge._services = {
            default_workspace: default_service,
            requested_workspace: requested_service,
        }

        workspace_result = await getattr(bridge, bridge_method)(
            "Workspace goal",
            workspace=str(requested_workspace),
        )
        default_result = await getattr(bridge, bridge_method)("Default goal")

        assert workspace_result["id"] == "msn-requested"
        assert workspace_result["status"] == workspace_status
        assert default_result["id"] == "msn-default"
        assert default_result["status"] == default_status
        getattr(requested_service, service_method).assert_awaited_once_with(
            goal="Workspace goal",
            context="",
        )
        getattr(default_service, service_method).assert_awaited_once_with(
            goal="Default goal",
            context="",
        )
        assert requested_service.workspace == requested_workspace
        assert requested_service.store.store_path == requested_workspace / "missions.json"
        assert requested_service.planner.workspace == requested_workspace
        assert requested_service.executor.workspace == requested_workspace
        assert default_service.workspace == default_workspace
        assert default_service.store.store_path == default_workspace / "missions.json"
        assert default_service.planner.workspace == default_workspace
        assert default_service.executor.workspace == default_workspace

    @pytest.mark.asyncio
    async def test_non_default_mission_actions_use_owning_workspace_service(self, tmp_path):
        from src.server.services.mission_bridge import MissionBridge

        bridge = MissionBridge.get_instance()
        default_service, workspace_service, mission = self._seed_non_default_mission_services(
            bridge,
            tmp_path,
        )

        assert await bridge.approve(mission.id) is True
        assert await bridge.cancel(mission.id) is True
        assert await bridge.pause(mission.id) is True
        assert await bridge.resume(mission.id) is True
        assert await bridge.status(mission.id) == "## Mission: Workspace mission\nStatus: running"
        assert await bridge.get_status_payload(mission.id) == {
            "mission_id": mission.id,
            "status_text": "## Mission: Workspace mission\nStatus: running",
        }

        workspace_service.confirm_mission.assert_awaited_once_with(mission.id)
        workspace_service.cancel_mission.assert_awaited_once_with(mission.id)
        workspace_service.pause_mission.assert_awaited_once_with(mission.id)
        workspace_service.resume_mission.assert_awaited_once_with(mission.id)
        assert workspace_service.format_status.call_count == 2
        default_service.confirm_mission.assert_not_called()
        default_service.cancel_mission.assert_not_called()
        default_service.pause_mission.assert_not_called()
        default_service.resume_mission.assert_not_called()
        default_service.format_status.assert_not_called()

    def test_non_default_mission_reads_and_payloads_use_owning_workspace_service(self, tmp_path):
        from src.server.services.mission_bridge import MissionBridge

        bridge = MissionBridge.get_instance()
        default_service, workspace_service, mission = self._seed_non_default_mission_services(
            bridge,
            tmp_path,
        )

        assert bridge.get_mission_raw(mission.id) is mission
        assert bridge.get_mission_detail(mission.id)["id"] == mission.id
        assert bridge.get_log(mission.id, tail=1) == ["[10:01:00] Workspace log 2"]
        assert bridge.get_mission_log_payload(mission.id, tail=1) == {
            "mission_id": mission.id,
            "entries": ["[10:01:00] Workspace log 2"],
            "count": 1,
        }

        assert default_service.get_mission.call_count >= 1
        assert workspace_service.get_mission.call_count >= 1

    @pytest.mark.asyncio
    async def test_approve_delegates_to_service(self):
        from src.server.services.mission_bridge import MissionBridge

        bridge = MissionBridge.get_instance()
        mock_service = MagicMock()
        mock_service.confirm_mission = AsyncMock(return_value=True)
        self._set_default_service(bridge, mock_service)

        result = await bridge.approve("msn-test1234")
        assert result is True
        mock_service.confirm_mission.assert_called_once_with("msn-test1234")

    @pytest.mark.asyncio
    async def test_cancel_delegates_to_service(self):
        from src.server.services.mission_bridge import MissionBridge

        bridge = MissionBridge.get_instance()
        mock_service = MagicMock()
        mock_service.cancel_mission = AsyncMock(return_value=True)
        self._set_default_service(bridge, mock_service)

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
        self._set_default_service(bridge, mock_service)

        result = await bridge.status("msn-test1234")
        assert "Mission: Test goal" in result

    @pytest.mark.asyncio
    async def test_status_returns_none_for_missing(self):
        from src.server.services.mission_bridge import MissionBridge

        bridge = MissionBridge.get_instance()
        mock_service = MagicMock()
        mock_service.get_mission.return_value = None
        self._set_default_service(bridge, mock_service)

        result = await bridge.status("msn-nonexist")
        assert result is None

    def test_get_log_with_tail(self):
        from src.server.services.mission_bridge import MissionBridge

        bridge = MissionBridge.get_instance()
        mock_mission = self._make_mock_mission()
        mock_mission.log = [f"[10:0{i}:00] Entry {i}" for i in range(10)]

        mock_service = MagicMock()
        mock_service.get_mission.return_value = mock_mission
        self._set_default_service(bridge, mock_service)

        entries = bridge.get_log("msn-test1234", tail=3)
        assert len(entries) == 3
        assert "Entry 7" in entries[0]

    def test_get_log_missing_mission(self):
        from src.server.services.mission_bridge import MissionBridge

        bridge = MissionBridge.get_instance()
        mock_service = MagicMock()
        mock_service.get_mission.return_value = None
        self._set_default_service(bridge, mock_service)

        entries = bridge.get_log("msn-nonexist")
        assert entries == []


class TestMissionToDict:
    """Test the _mission_to_dict serializer."""

    def test_basic_mission_serialization(self):
        from src.server.services.mission_bridge import MissionBridge

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
