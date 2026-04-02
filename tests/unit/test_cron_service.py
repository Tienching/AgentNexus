from __future__ import annotations

import json

from src.nanobot.cron.service import CronService
from src.nanobot.cron.types import CronSchedule


def test_status_reports_degraded_state_for_invalid_json(tmp_path):
    store_path = tmp_path / "jobs.json"
    store_path.write_text('{"jobs": [', encoding="utf-8")

    service = CronService(store_path=store_path)

    status = service.status()

    assert service.list_jobs() == []
    assert status["jobs"] == 0
    assert status["degraded"] is True
    assert "Expecting value" in status["load_error"]


def test_status_reports_degraded_state_for_malformed_job_payload(tmp_path):
    store_path = tmp_path / "jobs.json"
    store_path.write_text(
        json.dumps(
            {
                "version": 1,
                "jobs": [
                    {
                        "id": "job-1",
                        "name": "broken",
                        "schedule": {"kind": "every", "everyMs": 1000},
                        "payload": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    service = CronService(store_path=store_path)

    status = service.status()

    assert service.list_jobs() == []
    assert status["jobs"] == 0
    assert status["degraded"] is True
    assert "NoneType" in status["load_error"]


def test_status_recovers_after_store_is_repaired(tmp_path):
    store_path = tmp_path / "jobs.json"
    store_path.write_text('{"jobs": [', encoding="utf-8")

    service = CronService(store_path=store_path)

    degraded_status = service.status()

    assert degraded_status["degraded"] is True
    assert degraded_status["jobs"] == 0

    repaired_store = {
        "version": 1,
        "jobs": [
            {
                "id": "job-1",
                "name": "healthy",
                "enabled": True,
                "schedule": {"kind": "every", "everyMs": 1000},
                "payload": {"kind": "agent_turn", "message": "hello", "deliver": False},
                "state": {},
                "createdAtMs": 1,
                "updatedAtMs": 1,
                "deleteAfterRun": False,
            }
        ],
    }
    store_path.write_text(json.dumps(repaired_store), encoding="utf-8")

    recovered_status = service.status()

    assert recovered_status["degraded"] is False
    assert recovered_status["load_error"] is None
    assert recovered_status["jobs"] == 1
    assert [job.name for job in service.list_jobs()] == ["healthy"]


def test_add_job_clears_prior_load_error_after_replacing_corrupt_store(tmp_path):
    store_path = tmp_path / "jobs.json"
    store_path.write_text('{"jobs": [', encoding="utf-8")

    service = CronService(store_path=store_path)

    assert service.status()["degraded"] is True

    service.add_job(
        name="new job",
        schedule=CronSchedule(kind="every", every_ms=1000),
        message="hello",
    )

    status = service.status()

    assert status["degraded"] is False
    assert status["load_error"] is None
    assert status["jobs"] == 1
