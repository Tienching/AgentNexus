# -*- coding: utf-8 -*-

import pytest

from src.nanobot.agent.queue import AgentTaskQueue, QueueReason
from src.runtime.models.task_models import TaskStatus
from src.runtime.stores.db import Database
from src.runtime.stores.task_storage import TaskQueue


@pytest.fixture
def task_queue_db(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "agent-task-queue.db"))
    Database.reset_instances()
    queue = TaskQueue(exec_user="test_agent")
    try:
        yield queue, queue._db
    finally:
        Database.reset_instances()


def test_pull_next_task_claims_pending_task(task_queue_db):
    task_queue, db = task_queue_db
    task = task_queue.add_task(description="Claim me")
    agent_queue = AgentTaskQueue(exec_user="test_agent", db=db)

    result = agent_queue.pull_next_task("worker-a")

    assert result.reason == QueueReason.ASSIGNED
    assert result.task is not None
    assert result.task.id == task.id
    assert result.task.status == TaskStatus.RUNNING
    assert result.task.assigned_to == "worker-a"

    stored = task_queue.get_task(task.id)
    assert stored.status == TaskStatus.RUNNING
    assert stored.assigned_to == "worker-a"


def test_pull_next_task_continues_running_task(task_queue_db):
    task_queue, db = task_queue_db
    task = task_queue.add_task(description="Continue me", assigned_to="worker-a")
    agent_queue = AgentTaskQueue(exec_user="test_agent", db=db)
    first = agent_queue.pull_next_task("worker-a")

    second = agent_queue.pull_next_task("worker-a")

    assert first.reason == QueueReason.ASSIGNED
    assert second.reason == QueueReason.CONTINUE_CURRENT
    assert second.task is not None
    assert second.task.id == task.id
    assert second.task.status == TaskStatus.RUNNING


def test_queue_depth_counts_claimable_pending_tasks(task_queue_db):
    task_queue, db = task_queue_db
    agent_queue = AgentTaskQueue(exec_user="test_agent", db=db)
    task_queue.add_task(description="Unassigned")
    assigned_to_a = task_queue.add_task(description="Assigned to A")
    assigned_to_b = task_queue.add_task(description="Assigned to B")
    running = task_queue.add_task(description="Running", assigned_to="worker-a")

    assert agent_queue.assign_task(assigned_to_a.id, "worker-a")
    assert agent_queue.assign_task(assigned_to_b.id, "worker-b")
    task_queue.start_task(running.id)

    assert task_queue.get_task(assigned_to_a.id).status == TaskStatus.PENDING
    assert task_queue.get_task(running.id).status == TaskStatus.RUNNING
    assert agent_queue.get_agent_queue_depth("worker-a") == 2
    assert agent_queue.get_agent_queue_depth("worker-b") == 2
    assert agent_queue.get_agent_queue_depth("worker-c") == 1


def test_pull_next_task_updates_runtime_claim_side_effects(task_queue_db):
    task_queue, db = task_queue_db
    task = task_queue.add_task(description="Claim side effects")
    agent_queue = AgentTaskQueue(exec_user="test_agent", db=db)

    result = agent_queue.pull_next_task("worker-a")

    assert result.reason == QueueReason.ASSIGNED
    stored = task_queue.get_task(task.id)
    assert stored.attempt_count == 1
    assert stored.runtime_status == "running"
    assert stored.runtime_last_heartbeat is not None


def test_concurrent_pull_next_task_does_not_exceed_capacity(task_queue_db):
    import threading

    task_queue, db = task_queue_db
    task_queue.add_task(description="First")
    task_queue.add_task(description="Second")
    agent_queue = AgentTaskQueue(exec_user="test_agent", db=db)
    barrier = threading.Barrier(2)
    results = []

    def pull():
        barrier.wait()
        results.append(agent_queue.pull_next_task("worker-a", max_capacity=1))

    threads = [threading.Thread(target=pull), threading.Thread(target=pull)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    running = [task for task in task_queue.get_running_tasks() if task.assigned_to == "worker-a"]
    assert len(running) == 1
    assert {result.reason for result in results} <= {QueueReason.ASSIGNED, QueueReason.CONTINUE_CURRENT}
