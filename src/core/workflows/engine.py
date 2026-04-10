# -*- coding: utf-8 -*-
"""Workflow and pipeline execution engine.

MC-022: Multi-step pipeline execution with status tracking.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


StepHandler = Callable[[Dict[str, Any]], Dict[str, Any]]


@dataclass
class WorkflowStep:
    name: str
    handler: StepHandler
    timeout_seconds: float = 60.0


@dataclass
class StepResult:
    step_name: str
    status: WorkflowStatus
    started_at: float
    ended_at: float
    output: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class WorkflowRun:
    id: str
    name: str
    status: WorkflowStatus
    input_context: Dict[str, Any]
    output_context: Dict[str, Any]
    steps: List[StepResult] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    ended_at: Optional[float] = None


class WorkflowEngine:
    """Simple serial workflow engine."""

    def __init__(self):
        self._pipelines: Dict[str, List[WorkflowStep]] = {}
        self._runs: Dict[str, WorkflowRun] = {}

    def register_pipeline(self, name: str, steps: List[WorkflowStep]) -> None:
        if not steps:
            raise ValueError("pipeline must contain at least one step")
        self._pipelines[name] = steps

    def list_pipelines(self) -> List[str]:
        return sorted(self._pipelines.keys())

    def run_pipeline(self, name: str, context: Optional[Dict[str, Any]] = None) -> WorkflowRun:
        if name not in self._pipelines:
            raise ValueError(f"unknown pipeline: {name}")

        run = WorkflowRun(
            id=f"wf-{uuid.uuid4().hex[:12]}",
            name=name,
            status=WorkflowStatus.RUNNING,
            input_context=dict(context or {}),
            output_context=dict(context or {}),
            started_at=time.time(),
        )
        self._runs[run.id] = run

        for step in self._pipelines[name]:
            started = time.time()
            try:
                output = step.handler(dict(run.output_context)) or {}
                if not isinstance(output, dict):
                    raise ValueError(f"step '{step.name}' must return dict")
                run.output_context.update(output)
                run.steps.append(
                    StepResult(
                        step_name=step.name,
                        status=WorkflowStatus.COMPLETED,
                        started_at=started,
                        ended_at=time.time(),
                        output=output,
                    )
                )
            except Exception as e:
                run.steps.append(
                    StepResult(
                        step_name=step.name,
                        status=WorkflowStatus.FAILED,
                        started_at=started,
                        ended_at=time.time(),
                        output={},
                        error=str(e),
                    )
                )
                run.status = WorkflowStatus.FAILED
                run.ended_at = time.time()
                return run

        run.status = WorkflowStatus.COMPLETED
        run.ended_at = time.time()
        return run

    def get_run(self, run_id: str) -> Optional[WorkflowRun]:
        return self._runs.get(run_id)

    def list_runs(self, pipeline_name: Optional[str] = None) -> List[WorkflowRun]:
        runs = list(self._runs.values())
        if pipeline_name:
            runs = [r for r in runs if r.name == pipeline_name]
        runs.sort(key=lambda r: r.started_at, reverse=True)
        return runs


_engine: Optional[WorkflowEngine] = None


def get_workflow_engine() -> WorkflowEngine:
    global _engine
    if _engine is None:
        _engine = WorkflowEngine()
    return _engine
