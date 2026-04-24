# -*- coding: utf-8 -*-
"""Tests for app-scoped service/container wiring."""

from __future__ import annotations

from src.runtime.history import HistoryService as RuntimeHistoryService
from src.runtime.stores.session_storage import SessionStorage as RuntimeSessionStorage
from src.runtime.stores.task_storage import TaskQueue as RuntimeTaskQueue
from src.server import services as service_exports
from src.server.services.app_container import get_app_container, reset_app_container
from src.server.services.history_service import get_history_service
from src.server.services.session_storage import get_session_storage
from src.server.services.task_storage import get_task_queue


def setup_function():
    reset_app_container()


def teardown_function():
    reset_app_container()


def test_session_storage_is_app_scoped_singleton():
    s1 = get_session_storage()
    s2 = get_session_storage()
    assert s1 is s2
    assert s1 is get_app_container().session_storage()


def test_task_queue_is_cached_per_exec_user():
    q1 = get_task_queue("alice")
    q2 = get_task_queue("alice")
    q3 = get_task_queue("bob")
    assert q1 is q2
    assert q1 is not q3


def test_history_service_comes_preloaded_with_default_parsers():
    history = get_app_container().history_service()
    assert history.registered_providers() == ["claude", "codebuddy", "codex", "gemini"]


def test_service_facades_export_canonical_runtime_types():
    assert service_exports.SessionStorage is RuntimeSessionStorage
    assert issubclass(service_exports.TaskQueue, RuntimeTaskQueue)
    assert service_exports.HistoryService is RuntimeHistoryService


def test_container_reset_discards_cached_singletons():
    container = get_app_container()
    session_storage = container.session_storage()
    history_service = container.history_service()
    task_queue = get_task_queue("alice")

    reset_app_container()

    fresh_container = get_app_container()
    fresh_session_storage = fresh_container.session_storage()
    fresh_history_service = get_history_service()
    fresh_task_queue = get_task_queue("alice")

    assert fresh_container is not container
    assert fresh_session_storage is not session_storage
    assert fresh_history_service is not history_service
    assert fresh_task_queue is not task_queue
    assert fresh_session_storage is get_session_storage()
    assert fresh_history_service is fresh_container.history_service()


def test_task_queue_normalizes_blank_exec_user_to_default():
    q1 = get_task_queue("")
    q2 = get_task_queue("   ")
    q3 = get_task_queue("default")

    assert q1 is q2 is q3
    assert q1.exec_user == "default"
