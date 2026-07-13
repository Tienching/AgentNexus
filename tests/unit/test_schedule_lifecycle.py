from datetime import datetime, timedelta, timezone

import pytest

from src.runtime.models.schedule_models import ScheduleStatus
from src.runtime.stores.db import Database
from src.runtime.stores.schedule_storage import ScheduleStorage


@pytest.fixture
def schedule_storage(tmp_path):
    db = Database(str(tmp_path / "schedule-lifecycle.db"))
    db.ensure_migrated()
    yield ScheduleStorage(exec_user="ubuntu", db=db)
    Database.reset_instances()


def test_one_time_schedule_becomes_terminal_after_first_run(schedule_storage):
    schedule = schedule_storage.add_schedule(
        name="run once",
        description="single run",
        run_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )

    schedule_storage.record_run(schedule, "task-001")

    stored = schedule_storage.get_schedule(schedule.id)
    assert stored is not None
    assert stored.status == ScheduleStatus.CANCELLED
    assert stored.run_count == 1
    assert stored.next_run_at is None
    assert stored.cancelled_at is not None
    assert schedule_storage.list_schedules(status="active")[1] == 0
    assert schedule_storage.list_schedules(status="cancelled")[1] == 1
