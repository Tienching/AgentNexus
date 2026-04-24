# -*- coding: utf-8 -*-

from src.core.reports.standup import StandupReportGenerator
from src.runtime.models.task_models import TaskStatus
from src.runtime.stores.db import Database
from src.runtime.stores.task_storage import TaskQueue


def test_standup_counts_running_tasks(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "standup.db"))
    Database.reset_instances()
    try:
        task_queue = TaskQueue(exec_user="standup_user")
        running = task_queue.add_task(description="Running task", assigned_to="worker-a")
        pending = task_queue.add_task(description="Pending task", assigned_to="worker-a")
        task_queue.start_task(running.id)

        report = StandupReportGenerator().generate_report(date="2026-04-24")

        assert task_queue.get_task(running.id).status == TaskStatus.RUNNING
        assert task_queue.get_task(pending.id).status == TaskStatus.PENDING
        assert report.total_tasks_in_progress == 1
        assert report.agent_stats["worker-a"].tasks_in_progress == 1
    finally:
        Database.reset_instances()
