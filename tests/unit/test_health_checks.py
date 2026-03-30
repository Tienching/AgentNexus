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

import pytest
from unittest.mock import MagicMock, patch

from src.server.models.legacy import HealthCheck, HealthResponse
from src.server.routers.health import _worst, _check_redis, _check_process_memory, _check_disk_space, _perform_health_check


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
        hr = HealthResponse(status="healthy", service="nexus", version="0.1.0")
        assert hr.checks == []

    def test_uptime_seconds_defaults_to_none(self):
        hr = HealthResponse(status="healthy", service="nexus", version="0.1.0")
        assert hr.uptime_seconds is None

    def test_checks_field_accepts_list(self):
        hc = HealthCheck(name="Redis", status="healthy", message="OK")
        hr = HealthResponse(status="healthy", service="nexus", version="0.1.0", checks=[hc])
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
        import resource
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
        assert result.version == "0.1.0"

    def test_uptime_seconds_is_non_negative(self):
        healthy = HealthCheck(name="X", status="healthy", message="OK")
        with patch("src.server.routers.health._check_redis", return_value=healthy), \
             patch("src.server.routers.health._check_process_memory", return_value=healthy), \
             patch("src.server.routers.health._check_disk_space", return_value=healthy):
            result = _perform_health_check()
        assert result.uptime_seconds is not None
        assert result.uptime_seconds >= 0


# ---------------------------------------------------------------------------
# /health route — async integration
# ---------------------------------------------------------------------------

class TestHealthRoute:
    @pytest.mark.asyncio
    async def test_health_route_returns_health_response(self):
        from src.server.routers.health import health_check
        healthy = HealthCheck(name="X", status="healthy", message="OK")
        with patch("src.server.routers.health._perform_health_check",
                   return_value=HealthResponse(status="healthy", service="agent-nexus",
                                               version="0.1.0", checks=[healthy])):
            result = await health_check()
        assert isinstance(result, HealthResponse)
        assert result.status == "healthy"
        assert len(result.checks) == 1

    @pytest.mark.asyncio
    async def test_health_route_degraded_when_redis_down(self):
        from src.server.routers.health import health_check
        bad = HealthCheck(name="Redis", status="unhealthy", message="down")
        with patch("src.server.routers.health._perform_health_check",
                   return_value=HealthResponse(status="unhealthy", service="agent-nexus",
                                               version="0.1.0", checks=[bad])):
            result = await health_check()
        assert result.status == "unhealthy"
