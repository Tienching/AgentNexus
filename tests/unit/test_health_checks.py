# -*- coding: utf-8 -*-
"""Tests for the enhanced /health endpoint.

Ported from mission-control performHealthCheck (commits 4eda03a / afa8e9d).

Covers:
- HealthCheck and HealthResponse model shapes
- _worst() status aggregation
- _check_redis(): healthy, slow (warning), unreachable (unhealthy)
- _check_process_memory(): healthy, warning, critical
- _check_disk_space(): healthy, warning, critical, subprocess failure
- _perform_health_check(): aggregation, overall status propagation
- /health route integration
"""
from __future__ import annotations

import io
import json
import urllib.error
from types import SimpleNamespace

import pytest
from unittest.mock import MagicMock, patch

from src.runtime import __version__ as RUNTIME_VERSION
from src.server.models.legacy import HealthCheck, HealthResponse
from src.server.routers.health import (
    _build_health_error_response,
    _check_disk_space,
    _check_process_memory,
    _check_redis,
    _perform_health_check,
    _worst,
)


# ---------------------------------------------------------------------------
# HealthCheck model
# ---------------------------------------------------------------------------

class TestHealthCheckModel:
    def test_name_and_status_required(self):
        hc = HealthCheck(name="Redis", status="healthy")
        assert hc.name == "Redis"
        assert hc.status == "healthy"

    def test_message_defaults_to_empty_string(self):
        hc = HealthCheck(name="Redis", status="healthy")
        assert hc.message == ""

    def test_detail_defaults_to_none(self):
        hc = HealthCheck(name="Redis", status="healthy")
        assert hc.detail is None

    def test_detail_can_carry_dict(self):
        hc = HealthCheck(name="Redis", status="healthy", detail={"latency_ms": 2.1})
        assert hc.detail["latency_ms"] == 2.1


class TestHealthResponseModel:
    def test_checks_defaults_to_empty_list(self):
        hr = HealthResponse(status="healthy", service="nexus", version=RUNTIME_VERSION)
        assert hr.checks == []

    def test_uptime_seconds_defaults_to_none(self):
        hr = HealthResponse(status="healthy", service="nexus", version=RUNTIME_VERSION)
        assert hr.uptime_seconds is None

    def test_checks_field_accepts_list(self):
        hc = HealthCheck(name="Redis", status="healthy", message="OK")
        hr = HealthResponse(status="healthy", service="nexus", version=RUNTIME_VERSION, checks=[hc])
        assert len(hr.checks) == 1


# ---------------------------------------------------------------------------
# _worst() — status aggregation
# ---------------------------------------------------------------------------

class TestWorstStatus:
    def test_all_healthy_returns_healthy(self):
        assert _worst(["healthy", "healthy"]) == "healthy"

    def test_one_warning_beats_healthy(self):
        assert _worst(["healthy", "warning"]) == "warning"

    def test_unhealthy_beats_warning(self):
        assert _worst(["warning", "unhealthy"]) == "unhealthy"

    def test_critical_beats_all(self):
        assert _worst(["healthy", "warning", "unhealthy", "critical"]) == "critical"

    def test_error_rank_above_unhealthy(self):
        assert _worst(["unhealthy", "error"]) == "error"

    def test_empty_list_returns_healthy(self):
        assert _worst([]) == "healthy"

    def test_single_status_returned_unchanged(self):
        assert _worst(["degraded"]) == "degraded"


# ---------------------------------------------------------------------------
# _check_redis()
# ---------------------------------------------------------------------------

class TestCheckRedis:
    @patch("src.server.routers.health.get_redis_client")
    def test_healthy_ping_returns_healthy(self, mock_get_redis, monkeypatch):
        r = MagicMock()
        r.ping.return_value = True
        mock_get_redis.return_value = r
        # Make time.monotonic return fast elapsed
        monkeypatch.setattr("src.server.routers.health.time.monotonic", lambda: 0.0)
        # Two calls: t0 and t1 (elapsed = 0 ms)
        calls = [0.0, 0.001]
        idx = [0]
        def mock_mono():
            v = calls[idx[0]]
            idx[0] += 1
            return v
        monkeypatch.setattr("src.server.routers.health.time.monotonic", mock_mono)

        result = _check_redis()
        assert result.status == "healthy"
        assert result.name == "Redis"
        assert "reachable" in result.message

    @patch("src.server.routers.health.get_redis_client")
    def test_slow_ping_returns_warning(self, mock_get_redis, monkeypatch):
        r = MagicMock()
        r.ping.return_value = True
        mock_get_redis.return_value = r
        calls = [0.0, 0.15]  # 150 ms
        idx = [0]
        def mock_mono():
            v = calls[idx[0]]
            idx[0] += 1
            return v
        monkeypatch.setattr("src.server.routers.health.time.monotonic", mock_mono)

        result = _check_redis()
        assert result.status == "warning"
        assert "slow" in result.message.lower()

    @patch("src.server.routers.health.get_redis_client")
    def test_ping_exception_returns_unhealthy(self, mock_get_redis):
        r = MagicMock()
        r.ping.side_effect = ConnectionError("refused")
        mock_get_redis.return_value = r

        result = _check_redis()
        assert result.status == "unhealthy"
        assert "refused" in result.message.lower() or "connectivity" in result.message.lower()


# ---------------------------------------------------------------------------
# _check_process_memory()
# ---------------------------------------------------------------------------

class TestCheckProcessMemory:
    def _run_with_rss(self, rss_bytes: int):
        """Run _check_process_memory with a patched RSS value."""
        fake_usage = MagicMock()
        fake_usage.ru_maxrss = rss_bytes  # Linux: kilobytes

        with patch("src.server.routers.health.resource.getrusage", return_value=fake_usage), \
             patch("src.server.routers.health.os.uname") as mock_uname:
            mock_uname.return_value = MagicMock(sysname="Linux")
            return _check_process_memory()

    def test_low_memory_healthy(self):
        result = self._run_with_rss(100 * 1024)  # 100 MB in kB
        assert result.status == "healthy"
        assert result.name == "Process Memory"

    def test_medium_memory_warning(self):
        result = self._run_with_rss(500 * 1024)  # 500 MB in kB
        assert result.status == "warning"

    def test_high_memory_critical(self):
        result = self._run_with_rss(900 * 1024)  # 900 MB in kB
        assert result.status == "critical"

    def test_detail_contains_rss_mb(self):
        result = self._run_with_rss(200 * 1024)  # 200 MB
        assert result.detail is not None
        assert result.detail["rss_mb"] == 200.0


# ---------------------------------------------------------------------------
# _check_disk_space()
# ---------------------------------------------------------------------------

class TestCheckDiskSpace:
    def _run_with_df_output(self, df_output: str):
        with patch("src.server.routers.health.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=df_output, returncode=0)
            return _check_disk_space()

    def test_low_usage_healthy(self):
        df = "Filesystem      Size  Used Avail Use% Mounted on\n/dev/sda1        50G   20G   30G  40% /\n"
        result = self._run_with_df_output(df)
        assert result.status == "healthy"
        assert "40%" in result.message

    def test_90_pct_usage_warning(self):
        df = "Filesystem      Size  Used Avail Use% Mounted on\n/dev/sda1        50G   45G    5G  90% /\n"
        result = self._run_with_df_output(df)
        assert result.status == "warning"

    def test_95_pct_usage_critical(self):
        df = "Filesystem      Size  Used Avail Use% Mounted on\n/dev/sda1        50G   48G    2G  96% /\n"
        result = self._run_with_df_output(df)
        assert result.status == "critical"

    def test_subprocess_failure_returns_error(self):
        with patch("src.server.routers.health.subprocess.run", side_effect=OSError("df not found")):
            result = _check_disk_space()
        assert result.status == "error"
        assert "disk space" in result.message.lower() or "failed" in result.message.lower()

    def test_detail_contains_usage_percent(self):
        df = "Filesystem      Size  Used Avail Use% Mounted on\n/dev/sda1        50G   10G   40G  20% /\n"
        result = self._run_with_df_output(df)
        assert result.detail is not None
        assert result.detail["usage_percent"] == 20


# ---------------------------------------------------------------------------
# _perform_health_check() — aggregation
# ---------------------------------------------------------------------------

class TestPerformHealthCheck:
    def test_all_healthy_returns_healthy(self):
        healthy = HealthCheck(name="X", status="healthy", message="OK")
        with patch("src.server.routers.health._check_redis", return_value=healthy), \
             patch("src.server.routers.health._check_process_memory", return_value=healthy), \
             patch("src.server.routers.health._check_disk_space", return_value=healthy):
            result = _perform_health_check()
        assert result.status == "healthy"
        assert len(result.checks) == 3

    def test_includes_startup_subsystem_checks(self):
        healthy = HealthCheck(name="X", status="healthy", message="OK")
        startup_states = {
            "task_executor": {
                "name": "Task Executor",
                "status": "healthy",
                "message": "Started",
                "required": True,
                "detail": {"phase": "startup"},
            },
            "channel_service": {
                "name": "Channel Service",
                "status": "healthy",
                "message": "No channels configured",
                "required": False,
                "detail": {"configured": False},
            },
        }
        with patch("src.server.routers.health._check_redis", return_value=healthy), \
             patch("src.server.routers.health._check_process_memory", return_value=healthy), \
             patch("src.server.routers.health._check_disk_space", return_value=healthy):
            result = _perform_health_check(startup_states=startup_states)

        checks_by_name = {check.name: check for check in result.checks}
        assert checks_by_name["Task Executor"].status == "healthy"
        assert checks_by_name["Task Executor"].detail["phase"] == "startup"
        assert checks_by_name["Channel Service"].detail["configured"] is False

    def test_failed_required_startup_subsystem_degrades_overall(self):
        healthy = HealthCheck(name="X", status="healthy", message="OK")
        startup_states = {
            "task_executor": {
                "name": "Task Executor",
                "status": "unhealthy",
                "message": "Startup failed: executor boom",
                "required": True,
                "detail": {"error": "executor boom"},
            }
        }
        with patch("src.server.routers.health._check_redis", return_value=healthy), \
             patch("src.server.routers.health._check_process_memory", return_value=healthy), \
             patch("src.server.routers.health._check_disk_space", return_value=healthy):
            result = _perform_health_check(startup_states=startup_states)

        assert result.status == "unhealthy"
        assert any(
            check.name == "Task Executor"
            and check.status == "unhealthy"
            and check.detail["error"] == "executor boom"
            for check in result.checks
        )

    def test_failed_optional_startup_subsystem_does_not_degrade_overall(self):
        healthy = HealthCheck(name="X", status="healthy", message="OK")
        startup_states = {
            "channel_service": {
                "name": "Channel Service",
                "status": "unhealthy",
                "message": "Startup failed: missing token",
                "required": False,
                "detail": {"configured": True},
            }
        }
        with patch("src.server.routers.health._check_redis", return_value=healthy), \
             patch("src.server.routers.health._check_process_memory", return_value=healthy), \
             patch("src.server.routers.health._check_disk_space", return_value=healthy):
            result = _perform_health_check(startup_states=startup_states)

        assert result.status == "healthy"
        assert any(
            check.name == "Channel Service"
            and check.status == "unhealthy"
            and check.detail["required"] is False
            for check in result.checks
        )

    def test_one_warning_degrades_overall(self):
        healthy = HealthCheck(name="X", status="healthy", message="OK")
        warn = HealthCheck(name="Redis", status="warning", message="slow")
        with patch("src.server.routers.health._check_redis", return_value=warn), \
             patch("src.server.routers.health._check_process_memory", return_value=healthy), \
             patch("src.server.routers.health._check_disk_space", return_value=healthy):
            result = _perform_health_check()
        assert result.status == "warning"

    def test_unhealthy_redis_propagates(self):
        healthy = HealthCheck(name="X", status="healthy", message="OK")
        bad = HealthCheck(name="Redis", status="unhealthy", message="down")
        with patch("src.server.routers.health._check_redis", return_value=bad), \
             patch("src.server.routers.health._check_process_memory", return_value=healthy), \
             patch("src.server.routers.health._check_disk_space", return_value=healthy):
            result = _perform_health_check()
        assert result.status == "unhealthy"

    def test_response_has_service_and_version(self):
        healthy = HealthCheck(name="X", status="healthy", message="OK")
        with patch("src.server.routers.health._check_redis", return_value=healthy), \
             patch("src.server.routers.health._check_process_memory", return_value=healthy), \
             patch("src.server.routers.health._check_disk_space", return_value=healthy):
            result = _perform_health_check()
        assert result.service == "agent-nexus"
        assert result.version == RUNTIME_VERSION

    def test_uptime_seconds_is_non_negative(self):
        healthy = HealthCheck(name="X", status="healthy", message="OK")
        with patch("src.server.routers.health._check_redis", return_value=healthy), \
             patch("src.server.routers.health._check_process_memory", return_value=healthy), \
             patch("src.server.routers.health._check_disk_space", return_value=healthy):
            result = _perform_health_check()
        assert result.uptime_seconds is not None
        assert result.uptime_seconds >= 0


# ---------------------------------------------------------------------------
# Structured health route error payloads
# ---------------------------------------------------------------------------

class TestHealthErrorPayload:
    def test_build_health_error_response_contains_actionable_hint(self):
        payload = _build_health_error_response(RuntimeError("redis boot failed"))

        assert payload.status == "error"
        assert payload.checks[0].detail["hint"]
        assert payload.checks[0].detail["exception_type"] == "RuntimeError"


# ---------------------------------------------------------------------------
# /health route — async integration
# ---------------------------------------------------------------------------

class TestHealthRoute:
    @pytest.mark.asyncio
    async def test_health_route_returns_health_response(self):
        from src.server.routers.health import health_check

        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(startup_subsystems={})))
        healthy = HealthCheck(name="X", status="healthy", message="OK")
        with patch(
            "src.server.routers.health._perform_health_check",
            return_value=HealthResponse(
                status="healthy",
                service="agent-nexus",
                version=RUNTIME_VERSION,
                checks=[healthy],
            ),
        ):
            result = await health_check(request)

        assert isinstance(result, HealthResponse)
        assert result.status == "healthy"
        assert len(result.checks) == 1

    @pytest.mark.asyncio
    async def test_health_route_degraded_when_redis_down(self):
        from src.server.routers.health import health_check

        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(startup_subsystems={})))
        bad = HealthCheck(name="Redis", status="unhealthy", message="down")
        with patch(
            "src.server.routers.health._perform_health_check",
            return_value=HealthResponse(
                status="unhealthy",
                service="agent-nexus",
                version=RUNTIME_VERSION,
                checks=[bad],
            ),
        ):
            result = await health_check(request)

        assert result.status == "unhealthy"

    @pytest.mark.asyncio
    async def test_health_route_returns_structured_error_response(self):
        from fastapi.responses import JSONResponse
        from src.server.routers.health import health_check

        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(startup_subsystems={})))
        with patch(
            "src.server.routers.health._perform_health_check",
            side_effect=RuntimeError("redis boot failed"),
        ):
            result = await health_check(request)

        assert isinstance(result, JSONResponse)
        assert result.status_code == 503
        payload = json.loads(result.body)
        assert payload["status"] == "error"
        assert payload["checks"][0]["detail"]["hint"]

    @pytest.mark.asyncio
    async def test_health_route_reads_startup_states_from_app_state(self):
        from src.server.routers.health import health_check

        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    startup_subsystems={
                        "task_executor": {
                            "name": "Task Executor",
                            "status": "unhealthy",
                            "message": "Startup failed: executor boom",
                            "required": True,
                            "detail": {"error": "executor boom"},
                        }
                    }
                )
            )
        )
        healthy = HealthCheck(name="Redis", status="healthy", message="OK")

        with patch("src.server.routers.health._check_redis", return_value=healthy), \
             patch("src.server.routers.health._check_process_memory", return_value=healthy), \
             patch("src.server.routers.health._check_disk_space", return_value=healthy):
            result = await health_check(request)

        assert result.status == "unhealthy"
        assert any(
            check.name == "Task Executor" and check.detail["error"] == "executor boom"
            for check in result.checks
        )


class TestHealthCliStatus:
    def _build_command(self):
        from src.runtime.plugins.cli.commands.status import StatusCommand

        command = StatusCommand()
        command.env_manager.load_env = MagicMock(
            return_value={"API_HOST": "127.0.0.1", "API_PORT": "8081"}
        )
        return command

    def test_get_health_status_reads_structured_success_payload(self):
        command = self._build_command()
        payload = {
            "status": "warning",
            "checks": [{"name": "Redis", "status": "warning", "message": "Redis slow"}],
        }
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(payload).encode()
        response.status = 200

        with patch("urllib.request.urlopen", return_value=response):
            health = command._get_health_status()

        assert health["status"] == "warning"
        assert health["checks"][0]["name"] == "Redis"
        assert health["code"] == 200

    def test_get_health_status_handles_invalid_json(self):
        command = self._build_command()
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b"not-json"
        response.status = 200

        with patch("urllib.request.urlopen", return_value=response):
            health = command._get_health_status()

        assert health["status"] == "error"
        assert "invalid JSON" in health["error"]
        assert health["checks"][0]["detail"]["hint"]

    def test_get_health_status_reads_structured_http_error_payload(self):
        command = self._build_command()
        body = json.dumps(
            {
                "status": "error",
                "error": "runtime dependencies unavailable",
                "checks": [
                    {
                        "name": "Health Endpoint",
                        "status": "error",
                        "message": "runtime dependencies unavailable",
                        "detail": {"hint": "restart redis"},
                    }
                ],
            }
        ).encode()
        error = urllib.error.HTTPError(
            url="http://127.0.0.1:8081/health",
            code=503,
            msg="Service Unavailable",
            hdrs=None,
            fp=io.BytesIO(body),
        )

        with patch("urllib.request.urlopen", side_effect=error):
            health = command._get_health_status()

        assert health["status"] == "error"
        assert health["code"] == 503
        assert health["checks"][0]["detail"]["hint"] == "restart redis"

    def test_get_health_status_builds_hint_when_endpoint_unreachable(self):
        command = self._build_command()
        unreachable = urllib.error.URLError("connection refused")

        with patch("urllib.request.urlopen", side_effect=unreachable):
            health = command._get_health_status()

        assert health["status"] == "unhealthy"
        assert "connection refused" in health["error"]
        assert health["checks"][0]["detail"]["hint"]
