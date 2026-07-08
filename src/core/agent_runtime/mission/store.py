"""JSON file persistence for missions."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from loguru import logger

from src.core.agent_runtime.mission.types import (
    Mission,
    MissionConfig,
    MissionOrigin,
    MissionStore,
    Milestone,
    Task,
    TaskResult,
    TokenUsage,
)


class MissionFileStore:
    """Persistent JSON file store for missions, following CronService pattern."""

    def __init__(self, store_path: Path):
        self.store_path = store_path
        self._store: MissionStore | None = None
        self._last_mtime: float = 0.0

    def _load_store(self) -> MissionStore:
        """Load missions from disk with mtime-based cache invalidation."""
        if self._store and self.store_path.exists():
            mtime = self.store_path.stat().st_mtime
            if mtime != self._last_mtime:
                logger.info("Missions: missions.json modified externally, reloading")
                self._store = None
        if self._store:
            return self._store

        if self.store_path.exists():
            try:
                data = json.loads(self.store_path.read_text(encoding="utf-8"))
                self._store = _deserialize_store(data)
            except Exception as e:
                logger.warning("Failed to load mission store: {}", e)
                self._store = MissionStore()
        else:
            self._store = MissionStore()

        if self.store_path.exists():
            self._last_mtime = self.store_path.stat().st_mtime
        return self._store

    def _save_store(self) -> None:
        """Save missions to disk atomically."""
        if not self._store:
            return
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        data = _serialize_store(self._store)
        content = json.dumps(data, indent=2, ensure_ascii=False)
        # Atomic write: temp file + rename
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.store_path.parent), suffix=".tmp"
        )
        try:
            os.write(fd, content.encode("utf-8"))
            os.close(fd)
            os.replace(tmp_path, str(self.store_path))
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        self._last_mtime = self.store_path.stat().st_mtime

    def load(self) -> MissionStore:
        return self._load_store()

    def save(self) -> None:
        self._save_store()

    def get_mission(self, mission_id: str) -> Mission | None:
        store = self._load_store()
        return next((m for m in store.missions if m.id == mission_id), None)

    def add_mission(self, mission: Mission) -> None:
        store = self._load_store()
        store.missions.append(mission)
        self._save_store()

    def update_mission(self, mission: Mission) -> None:
        store = self._load_store()
        for i, m in enumerate(store.missions):
            if m.id == mission.id:
                store.missions[i] = mission
                break
        self._save_store()

    def list_missions(self, include_completed: bool = True) -> list[Mission]:
        store = self._load_store()
        if include_completed:
            return list(store.missions)
        return [m for m in store.missions if m.status not in ("completed", "cancelled")]

    def remove_mission(self, mission_id: str) -> bool:
        store = self._load_store()
        before = len(store.missions)
        store.missions = [m for m in store.missions if m.id != mission_id]
        removed = len(store.missions) < before
        if removed:
            self._save_store()
        return removed


def _serialize_token_usage(u: TokenUsage) -> dict[str, Any]:
    return {
        "promptTokens": u.prompt_tokens,
        "completionTokens": u.completion_tokens,
        "totalTokens": u.total_tokens,
        "llmIterations": u.llm_iterations,
    }


def _serialize_task_result(r: TaskResult) -> dict[str, Any]:
    return {
        "status": r.status,
        "output": r.output,
        "error": r.error,
        "startedAtMs": r.started_at_ms,
        "completedAtMs": r.completed_at_ms,
        "retryCount": r.retry_count,
        "tokenUsage": _serialize_token_usage(r.token_usage),
    }


def _serialize_task(t: Task) -> dict[str, Any]:
    return {
        "id": t.id,
        "title": t.title,
        "description": t.description,
        "role": t.role,
        "status": t.status,
        "dependsOn": t.depends_on,
        "result": _serialize_task_result(t.result) if t.result else None,
        "maxRetries": t.max_retries,
        "maxIterations": t.max_iterations,
        "model": t.model,
    }


def _serialize_milestone(m: Milestone) -> dict[str, Any]:
    return {
        "id": m.id,
        "title": m.title,
        "description": m.description,
        "tasks": [_serialize_task(t) for t in m.tasks],
        "status": m.status,
        "validationCriteria": m.validation_criteria,
        "validationCommands": m.validation_commands,
        "validationTimeout": m.validation_timeout,
        "dependsOn": m.depends_on,
    }


def _serialize_mission(m: Mission) -> dict[str, Any]:
    return {
        "id": m.id,
        "goal": m.goal,
        "missionType": m.mission_type,
        "status": m.status,
        "milestones": [_serialize_milestone(ms) for ms in m.milestones],
        "origin": {"channel": m.origin.channel, "chatId": m.origin.chat_id},
        "config": {
            "maxParallelTasks": m.config.max_parallel_tasks,
            "autoReview": m.config.auto_review,
            "autoTest": m.config.auto_test,
            "taskTimeoutSeconds": m.config.task_timeout_seconds,
            "missionTimeoutSeconds": m.config.mission_timeout_seconds,
            "maxTotalIterations": m.config.max_total_iterations,
            "contextWindowTokens": m.config.context_window_tokens,
            "priorResultMaxChars": m.config.prior_result_max_chars,
            "roleModelMap": m.config.role_model_map,
        },
        "createdAtMs": m.created_at_ms,
        "updatedAtMs": m.updated_at_ms,
        "completedAtMs": m.completed_at_ms,
        "error": m.error,
        "log": m.log,
        "tokenUsage": _serialize_token_usage(m.token_usage),
    }


def _serialize_store(store: MissionStore) -> dict[str, Any]:
    return {
        "version": store.version,
        "missions": [_serialize_mission(m) for m in store.missions],
    }


def _deserialize_token_usage(d: dict[str, Any] | None) -> TokenUsage:
    if not d:
        return TokenUsage()
    return TokenUsage(
        prompt_tokens=d.get("promptTokens", 0),
        completion_tokens=d.get("completionTokens", 0),
        total_tokens=d.get("totalTokens", 0),
        llm_iterations=d.get("llmIterations", 0),
    )


def _deserialize_task_result(d: dict[str, Any]) -> TaskResult:
    return TaskResult(
        status=d.get("status", "pending"),
        output=d.get("output", ""),
        error=d.get("error"),
        started_at_ms=d.get("startedAtMs", 0),
        completed_at_ms=d.get("completedAtMs", 0),
        retry_count=d.get("retryCount", 0),
        token_usage=_deserialize_token_usage(d.get("tokenUsage")),
    )


def _deserialize_task(d: dict[str, Any]) -> Task:
    return Task(
        id=d["id"],
        title=d["title"],
        description=d.get("description", ""),
        role=d.get("role", "coder"),
        status=d.get("status", "pending"),
        depends_on=d.get("dependsOn", []),
        result=_deserialize_task_result(d["result"]) if d.get("result") else None,
        max_retries=d.get("maxRetries", 2),
        max_iterations=d.get("maxIterations", 25),
        model=d.get("model", ""),
    )


def _deserialize_milestone(d: dict[str, Any]) -> Milestone:
    return Milestone(
        id=d["id"],
        title=d["title"],
        description=d.get("description", ""),
        tasks=[_deserialize_task(t) for t in d.get("tasks", [])],
        status=d.get("status", "pending"),
        validation_criteria=d.get("validationCriteria", ""),
        validation_commands=d.get("validationCommands", []),
        validation_timeout=d.get("validationTimeout", 120),
        depends_on=d.get("dependsOn", []),
    )


def _deserialize_mission(d: dict[str, Any]) -> Mission:
    origin_d = d.get("origin", {})
    config_d = d.get("config", {})
    return Mission(
        id=d["id"],
        goal=d["goal"],
        mission_type=d.get("missionType", "general"),
        status=d.get("status", "planning"),
        milestones=[_deserialize_milestone(m) for m in d.get("milestones", [])],
        origin=MissionOrigin(
            channel=origin_d.get("channel", "cli"),
            chat_id=origin_d.get("chatId", "direct"),
        ),
        config=MissionConfig(
            max_parallel_tasks=config_d.get("maxParallelTasks", 3),
            auto_review=config_d.get("autoReview", True),
            auto_test=config_d.get("autoTest", True),
            task_timeout_seconds=config_d.get("taskTimeoutSeconds", 600),
            mission_timeout_seconds=config_d.get("missionTimeoutSeconds", 7200),
            max_total_iterations=config_d.get("maxTotalIterations", 200),
            context_window_tokens=config_d.get("contextWindowTokens", 100_000),
            prior_result_max_chars=config_d.get("priorResultMaxChars", 2000),
            role_model_map=config_d.get("roleModelMap", {}),
        ),
        created_at_ms=d.get("createdAtMs", 0),
        updated_at_ms=d.get("updatedAtMs", 0),
        completed_at_ms=d.get("completedAtMs", 0),
        error=d.get("error"),
        log=d.get("log", []),
        token_usage=_deserialize_token_usage(d.get("tokenUsage")),
    )


def _deserialize_store(data: dict[str, Any]) -> MissionStore:
    return MissionStore(
        version=data.get("version", 1),
        missions=[_deserialize_mission(m) for m in data.get("missions", [])],
    )
