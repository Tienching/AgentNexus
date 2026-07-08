# -*- coding: utf-8 -*-
"""Task execution service — full lifecycle of running a queued task.

Extracted from ``app.py task_handler()`` for Single-Responsibility compliance.
The function orchestrates:

1. Provider dispatch (via :mod:`src.providers.dispatcher`)
2. ``RequestModel`` construction from Task fields
3. CLI execution loop with stream-json → AG-UI event conversion
4. Ralph Loop keyword detection and re-queue signalling
5. CLI session ID persistence for future ``--resume``
6. Post-execution notification delivery
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from src.providers.dispatcher import normalize_provider, create_executor, create_adapter
from src.server.security.exec_user_guard import validate_exec_user_sync
from src.server.logger import get_logger
from src.server.services.observability import record_sampled_event, telemetry
from src.server.utils.ids import gen_run_id
from src.server.utils.error_sanitize import safe_error_message

if TYPE_CHECKING:
    from src.server.models import Task

logger = get_logger(__name__)

# Sentinel returned to the executor to signal a Ralph Loop re-queue.
RALPH_LOOP_RETRY_SIGNAL = "__RALPH_LOOP_RETRY__"

# ---------------------------------------------------------------------------
# Task model classification
# Ported from mission-control src/lib/task-dispatch.ts::classifyTaskModel()
#
# Selects the appropriate LLM model tier based on keyword signals in the
# task description and priority.  Only applied when the task does NOT already
# have an explicit model field set by the caller.
#
# Nexus priority mapping (vs mission-control):
#   mission-control  →  Nexus
#   critical         →  project   (top priority)
#   high             →  serious
#   low              →  thought   (experimental / low-stakes)
# ---------------------------------------------------------------------------

_COMPLEX_SIGNALS = [
    "debug", "diagnos", "architect", "design system", "security audit",
    "root cause", "investigate", "incident", "failure", "broken", "not working",
    "refactor", "migration", "performance optim", "why is",
]

_ROUTINE_SIGNALS = [
    "status check", "health check", "ping", "list ", "fetch ", "format",
    "rename", "move file", "read file", "update readme", "bump version",
    "send message", "post to", "notify", "summarize", "translate",
    "quick ", "simple ", "routine ", "minor ",
]


def classify_task_model(task: "Task") -> Optional[str]:
    """Infer the best LLM model for *task* from keyword signals.

    Returns a model name string to use, or ``None`` when no override is
    warranted (let the provider's default model handle it).

    Priority tiers (Nexus):
    - ``project``   → complex / high-stakes → claude-opus model
    - ``thought``   + routine keywords → cheap / fast → claude-haiku model
    - everything else → ``None`` (use configured default)

    This function is intentionally provider-agnostic: the model names below
    are the canonical Claude model IDs used by the nexus claude provider.
    Callers that target a different provider should pass an explicit model
    on the task object instead of relying on auto-classification.
    """
    # If the task already carries an explicit model, respect it.
    model_value = (getattr(task, "model", None) or "").strip()
    if model_value:
        return model_value

    text = (getattr(task, "description", "") or "").lower()
    priority = str(getattr(task, "priority", "") or "").lower()

    # project priority = highest urgency → complex model
    if priority == "project":
        return "claude-opus-4-6"

    # Keyword-driven complex signal → complex model
    if any(sig in text for sig in _COMPLEX_SIGNALS):
        return "claude-opus-4-6"

    # thought priority + routine keyword → cheap fast model
    if priority == "thought" and any(sig in text for sig in _ROUTINE_SIGNALS):
        return "claude-haiku-4-5-20251001"

    # Routine keyword with non-high priority → cheap fast model
    if any(sig in text for sig in _ROUTINE_SIGNALS) and priority not in ("serious", "project"):
        return "claude-haiku-4-5-20251001"

    # Default: no override — let the executor use its configured model
    return None


# ---------------------------------------------------------------------------
# Provider affinity scoring
# Ported from mission-control autoRouteInboxTasks() / scoreAgentForTask()
# (commit 1acbf8e).
#
# MC scores *named agents* (coder/researcher/reviewer/…) for task-text keyword
# match.  Nexus uses *provider names* (claude/codex/codebuddy/hermes) instead
# of agent roles.  The same keyword-affinity table and scoring algorithm are
# preserved; only the role→provider mapping changes.
#
# Provider affinity keywords:
#   claude     → broad reasoning / architecture / security / research
#   codex      → code / implement / api / function / test / ci / deploy
#   codebuddy  → quick / simple / format / rename / status / translate
#   hermes     → autonomous agent / ACP / tool-heavy implementation
# ---------------------------------------------------------------------------

_PROVIDER_AFFINITY: dict[str, list[str]] = {
    "claude": [
        "research", "investigate", "analyze", "audit", "review", "security",
        "architect", "design", "diagnos", "root cause", "incident", "explain",
        "why", "evaluate", "compare", "survey", "benchmark", "strategy",
        "document", "summarize",
    ],
    "codex": [
        "code", "implement", "test", "unit test", "fix", "bug", "patch",
        "ci", "pipeline", "deploy", "endpoint", "function", "class",
        "module", "integration", "regression", "coverage",
    ],
    "codebuddy": [
        "quick", "simple", "minor", "routine", "format", "rename", "move file",
        "read file", "update readme", "bump version", "send message", "notify",
        "translate", "ping", "list ", "fetch ", "status check",
    ],
    "hermes": [
        "agent", "autonomous", "acp", "tool", "tools", "multi-step",
        "investigate", "implement", "fix", "debug", "workflow", "orchestrate",
        "execute", "end-to-end", "e2e",
    ],
}


def score_provider_for_task(provider: str, task_text: str) -> int:
    """Score *provider* suitability for *task_text* using keyword affinity.

    Ported from mission-control ``scoreAgentForTask()`` (commit 1acbf8e).
    Returns a non-negative integer; higher is a better fit.  Returns 1 as
    the minimum non-zero score so any registered provider can serve as a
    fallback.

    Args:
        provider:   Lowercase provider name (``"claude"``, ``"codex"``, etc.)
        task_text:  Concatenated task description + project name, lower-cased
                    by the caller.

    Returns:
        Score ≥ 0.  0 means the provider is unknown / not in affinity table.
    """
    keywords = _PROVIDER_AFFINITY.get(provider, [])
    if not keywords:
        return 0  # unknown provider — let caller decide

    score = sum(10 for kw in keywords if kw in task_text)
    return max(score, 1)  # minimum 1 so any registered provider can be a fallback


def select_provider_for_task(task_text: str, available_providers: list[str]) -> Optional[str]:
    """Pick the best provider for *task_text* from *available_providers*.

    Ported from mission-control ``autoRouteInboxTasks()`` scoring loop
    (commit 1acbf8e).  Returns the highest-scoring provider, or ``None``
    when *available_providers* is empty.

    If all providers score identically (e.g., no affinity keywords match),
    the first provider in *available_providers* is returned as the default.

    Args:
        task_text:           Raw task description (will be lower-cased here).
        available_providers: Ordered list of provider names to score.

    Returns:
        Provider name string, or ``None`` if list is empty.
    """
    if not available_providers:
        return None

    text = task_text.lower()
    scored = [(p, score_provider_for_task(p, text)) for p in available_providers]
    # Stable sort: ties broken by original order (first registered wins)
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[0][0]


def _resolve_task_binding(task: "Task", storage) -> dict:
    """Resolve canonical execution binding fields for a task run.

    The returned mapping intentionally prefers the execution binding model
    over legacy task/session pseudo-session assumptions, while still falling
    back to historic fields for compatibility.
    """
    compat_hits: list[str] = []
    binding = getattr(task, "execution_binding", None)
    storage_binding = None

    base_session_id = (getattr(task, "session_id", None) or "").strip() or f"task_{task.id}"

    if binding is None and storage is not None:
        try:
            storage_binding = storage.get_execution_binding(base_session_id)
            if storage_binding:
                binding = storage_binding
                compat_hits.append("storage_binding_lookup")
        except Exception as e:
            logger.warning(
                "Task binding lookup failed",
                extra={"task_id": task.id, "session_id": base_session_id, "error": str(e)},
            )

    if binding is None and hasattr(task, "to_execution_binding"):
        try:
            binding = task.to_execution_binding()
            compat_hits.append("derived_from_task_fields")
        except Exception as e:
            logger.warning(
                "Task binding derivation failed",
                extra={"task_id": task.id, "error": str(e)},
            )
            binding = None

    provider = normalize_provider(
        getattr(binding, "provider", None)
        or getattr(task, "provider", None)
        or "claude"
    )
    alias = (getattr(binding, "alias", None) or getattr(task, "alias", None) or provider)
    exec_user = validate_exec_user_sync(getattr(binding, "exec_user", None) or getattr(task, "exec_user", None) or "ubuntu")
    work_dir = getattr(binding, "work_dir", None) or getattr(task, "workspace", None)
    source_session_id = getattr(binding, "source_session_id", None) or getattr(task, "source_session_id", None)
    session_kind = getattr(binding, "session_kind", None) or getattr(task, "session_kind", None) or "task"

    session_id = (getattr(binding, "session_id", None) or "").strip() or base_session_id

    cli_session_id = (
        getattr(binding, "cli_session_id", None)
        or getattr(task, "cli_session_id", None)
        or getattr(task, "claude_session_id", None)
    )

    if not cli_session_id and storage is not None:
        lookup_candidates = [session_id, source_session_id, base_session_id]
        for candidate in lookup_candidates:
            if not candidate:
                continue
            try:
                stored_cli = storage.get_cli_session_id(candidate)
            except Exception as e:
                logger.debug(
                    "Task CLI resume lookup failed",
                    extra={"task_id": task.id, "session_id": candidate, "error": str(e)},
                )
                continue
            if stored_cli:
                cli_session_id = stored_cli
                compat_hits.append("resume_storage_lookup")
                break

    if not cli_session_id:
        compat_hits.append("resume_fallback_to_provider_default")

    # Keep the task object aligned with the canonical binding so any later
    # persistence or notification logic sees the same identifiers.
    try:
        task.session_id = session_id
        task.provider = provider
        task.alias = alias
        task.exec_user = exec_user
        if work_dir:
            task.workspace = work_dir
        if source_session_id:
            task.source_session_id = source_session_id
        task.session_kind = session_kind
        if cli_session_id:
            task.cli_session_id = cli_session_id
            task.claude_session_id = cli_session_id
        if binding is None and hasattr(task, "to_execution_binding"):
            binding = task.to_execution_binding()
        elif binding is not None:
            binding.session_id = session_id
            binding.provider = provider
            binding.alias = alias
            binding.exec_user = exec_user
            binding.work_dir = work_dir
            binding.source_session_id = source_session_id
            binding.session_kind = session_kind
            binding.cli_session_id = cli_session_id
            binding.task_id = task.id
            binding.source_type = "task"
            if getattr(binding, "metadata", None) is None:
                binding.metadata = {}
            binding.metadata.update({
                "compat_hits": compat_hits,
            })
    except Exception as e:
        logger.debug(
            "Task binding normalization failed",
            extra={"task_id": task.id, "error": str(e)},
        )

    return {
        "binding": binding,
        "compat_hits": compat_hits,
        "session_id": session_id,
        "provider": provider,
        "alias": alias,
        "exec_user": exec_user,
        "work_dir": work_dir,
        "cli_session_id": cli_session_id,
        "source_session_id": source_session_id,
        "session_kind": session_kind,
        "used_storage_binding": storage_binding is not None,
    }


def _provision_task_workspace(task: "Task") -> Optional[str]:
    """Provision a task worktree from repo metadata when available."""
    explicit_worktree = (getattr(task, "worktree_path", None) or "").strip()
    if explicit_worktree and Path(explicit_worktree).exists():
        task.workspace = explicit_worktree
        return explicit_worktree

    repo_url = (getattr(task, "repo_url", None) or "").strip() or None
    repo_root_value = (getattr(task, "repo_root", None) or "").strip() or None
    if not repo_url and not repo_root_value:
        if explicit_worktree:
            raise FileNotFoundError(f"Configured task worktree does not exist: {explicit_worktree}")
        return (getattr(task, "workspace", None) or "").strip() or None

    from src.runtime.commands.slash.worktree import provision_cached_worktree

    tmp_base = None
    if explicit_worktree:
        tmp_base = Path(explicit_worktree).parent
    elif (getattr(task, "workspace", None) or "").strip():
        tmp_base = Path(str(task.workspace)).parent

    provisioned = provision_cached_worktree(
        task_id=str(task.id),
        repo_url=repo_url,
        repo_root=Path(repo_root_value) if repo_root_value else None,
        tmp_base=tmp_base or Path("/tmp"),
    )
    resolved_worktree = str(provisioned.worktree.worktree_dir)
    task.worktree_path = resolved_worktree
    task.workspace = resolved_worktree
    return resolved_worktree


async def execute_task(task: "Task", task_queue=None) -> Optional[str]:
    """Execute a queued task end-to-end.

    Returns ``None`` on success, an error string on failure, or
    :data:`RALPH_LOOP_RETRY_SIGNAL` when the task should be re-queued
    for another Ralph Loop iteration.
    """
    # Deferred imports to avoid circular dependency at module level.
    from src.server.models import RequestModel
    from src.server.services import get_session_storage
    from src.server.services.stream_archiver import create_archiver

    started_at = time.perf_counter()
    run_id = gen_run_id()

    try:
        _provision_task_workspace(task)
    except Exception as e:
        has_workspace_contract = any(
            str(getattr(task, field, None) or "").strip()
            for field in ("repo_url", "repo_root", "worktree_path")
        )
        log_method = logger.error if has_workspace_contract else logger.warning
        log_method(
            "Task workspace provisioning failed",
            extra={
                "task_id": getattr(task, "id", None),
                "repo_url": getattr(task, "repo_url", None),
                "repo_root": getattr(task, "repo_root", None),
                "worktree_path": getattr(task, "worktree_path", None),
                "error": str(e),
            },
        )
        if has_workspace_contract:
            return f"Task workspace provisioning failed: {e}"

    storage = get_session_storage()
    binding_info = _resolve_task_binding(task, storage)
    binding = binding_info["binding"]
    session_id = binding_info["session_id"]
    provider = binding_info["provider"]
    alias_value = binding_info["alias"]
    exec_user = binding_info["exec_user"]
    work_dir = binding_info["work_dir"]
    cli_session_id = binding_info["cli_session_id"]
    source_session_id = binding_info["source_session_id"]

    telemetry.increment("task_execution.started")
    for hit in binding_info["compat_hits"]:
        telemetry.increment(f"task_execution.compat.{hit}")
    record_sampled_event(
        "task_execution.binding_resolved",
        {
            "task_id": task.id,
            "session_id": session_id,
            "provider": provider,
            "alias": alias_value,
            "exec_user": exec_user,
            "work_dir": work_dir,
            "cli_session_id_present": bool(cli_session_id),
            "source_session_id": source_session_id,
            "compat_hits": binding_info["compat_hits"],
            "used_storage_binding": binding_info["used_storage_binding"],
        },
    )

    logger.info(
        "Executing task with resolved binding",
        extra={
            "task_id": task.id,
            "session_id": session_id,
            "provider": provider,
            "alias": alias_value,
            "exec_user": exec_user,
            "work_dir": work_dir,
            "cli_session_id_present": bool(cli_session_id),
            "source_session_id": source_session_id,
            "compat_hits": binding_info["compat_hits"],
        },
    )

    # ── Provider dispatch ─────────────────────────────────────────
    executor = create_executor(provider)

    # ── User prompt & context ─────────────────────────────────────
    ctx = getattr(task, "context", None) or {}

    logger.debug(f"Task {task.id} context debug", extra={
        "task_id": task.id,
        "context_keys": list(ctx.keys()) if ctx else [],
        "next_user_message_id": ctx.get("next_user_message_id", "<MISSING>"),
        "next_run_kind": ctx.get("next_run_kind", "<MISSING>"),
    })

    user_prompt = (ctx.get("next_user_message") or task.description or "").strip()

    # Apply smart model classification: if the task has no explicit model,
    # infer the best tier from task description + priority keywords.
    model_value = classify_task_model(task)

    # ── Build RequestModel ────────────────────────────────────────
    request = RequestModel(
        content=user_prompt,
        user=task.project_id or "task_executor",
        session_id=session_id,
        msg_id=run_id,
        cwd=work_dir or "",
        cwd_mode=ctx.get("cwd_mode", ""),
        run_kind=ctx.get("next_run_kind", ""),
        provider=provider,
        alias=alias_value,
        model=model_value,
        cli_session_id=cli_session_id,
    )

    # ── Archiver + session storage ────────────────────────────────
    archiver = create_archiver(
        thread_id=session_id,
        run_id=run_id,
        username=request.user or "task_executor",
        exec_user=exec_user,
        provider=provider,
        alias=alias_value,
        execution_binding=binding,
        source_session_id=source_session_id,
    )

    # Store control-plane binding for this task session.
    try:
        storage.upsert_execution_binding(
            session_id=session_id,
            cli_session_id=cli_session_id,
            provider=provider,
            alias=alias_value,
            exec_user=exec_user,
            work_dir=work_dir or None,
            source_type="task",
            source_session_id=source_session_id,
            task_id=task.id,
            session_kind=binding_info["session_kind"],
        )
    except Exception as e:
        logger.warning(
            "Failed to set execution binding for task",
            extra={"task_id": task.id, "session_id": session_id, "error": str(e)},
        )

    try:
        storage.set_task_id(session_id, task.id)
    except Exception as e:
        logger.debug(
            "Failed to persist task_id on session meta",
            extra={"task_id": task.id, "session_id": session_id, "error": str(e)},
        )

    # ── Adapter ───────────────────────────────────────────────────
    adapter = create_adapter(provider)
    adapter.init_state(thread_id=session_id, run_id=run_id)

    initial_user_msg_id = ctx.get("next_user_message_id") or f"task-user-{task.id}"
    initial_messages = [
        {
            "id": str(initial_user_msg_id),
            "role": "user",
            "content": user_prompt,
        }
    ]

    logger.debug(f"Task {task.id} initial_messages", extra={
        "initial_user_msg_id": initial_user_msg_id,
        "user_prompt_length": len(user_prompt) if user_prompt else 0,
        "run_kind": ctx.get("next_run_kind", ""),
    })

    # ── Helpers ───────────────────────────────────────────────────

    async def _archive_converted_sse(converted: str):
        if not converted:
            return
        for _evt in converted.split("\n\n"):
            _evt = _evt.strip()
            if not _evt.startswith("data:"):
                continue
            payload = _evt.replace("data:", "", 1).strip()
            if not payload:
                continue
            try:
                evt_obj = json.loads(payload)
                if isinstance(evt_obj, dict):
                    try:
                        await archiver.archive_event(evt_obj)
                    except Exception:
                        pass
            except Exception:
                continue

    # ── Execute ───────────────────────────────────────────────────
    _captured_cli_session_id = None
    _task_error = None
    _retry_requested = False

    try:
        await archiver.on_run_started(initial_messages)
        telemetry.increment("task_execution.run_started")

        start_event = adapter.create_start_event()
        if start_event:
            await _archive_converted_sse(start_event)

        async for output in executor.execute(request, exec_user, output_format="raw"):
            if not output:
                continue

            try:
                data = json.loads(output)
                if isinstance(data, dict) and data.get("type") == "error":
                    err_msg = data.get("message", "Unknown error")
                    telemetry.increment("task_execution.output_error")
                    try:
                        err_event = adapter.create_error_event(err_msg)
                        if err_event:
                            await _archive_converted_sse(err_event)
                    except Exception:
                        pass
                    return err_msg

                # Capture CLI session ID from init/system events
                if _captured_cli_session_id is None and isinstance(data, dict):
                    _sid = data.get("session_id") or data.get("thread_id")
                    if _sid and isinstance(_sid, str):
                        _captured_cli_session_id = _sid
                        logger.info(
                            "Captured CLI session ID for task",
                            extra={"task_id": task.id, "session_id": session_id, "cli_session_id": _sid},
                        )
                        telemetry.increment("task_execution.cli_session_captured")
                        record_sampled_event(
                            "task_execution.cli_session_captured",
                            {
                                "task_id": task.id,
                                "session_id": session_id,
                                "cli_session_id": _sid,
                                "provider": provider,
                            },
                        )

                converted = adapter.convert(data) if isinstance(data, dict) else None
                if converted:
                    await _archive_converted_sse(converted)

            except json.JSONDecodeError:
                continue
            except Exception:
                continue

        end_event = adapter.create_end_event()
        if end_event:
            await _archive_converted_sse(end_event)

        # ── Ralph Loop post-execution ─────────────────────────────
        result = _handle_ralph_loop(task, session_id, storage, task_queue)
        if result is not None:
            _retry_requested = True
            return result

        logger.info(
            "Task completed successfully",
            extra={"task_id": task.id, "session_id": session_id, "provider": provider, "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2)},
        )
        telemetry.increment("task_execution.completed")
        record_sampled_event(
            "task_execution.completed",
            {
                "task_id": task.id,
                "session_id": session_id,
                "provider": provider,
                "alias": alias_value,
                "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
            },
        )
        _task_error = None
        return None

    except asyncio.CancelledError:
        logger.warning(
            "Task execution cancelled",
            extra={"task_id": task.id, "session_id": session_id, "provider": provider},
        )
        telemetry.increment("task_execution.cancelled")
        raise
    except Exception as e:
        logger.error(
            "Task execution failed",
            extra={"task_id": task.id, "session_id": session_id, "provider": provider, "error": str(e)},
            exc_info=True,
        )
        telemetry.increment("task_execution.failed")
        record_sampled_event(
            "task_execution.failed",
            {
                "task_id": task.id,
                "session_id": session_id,
                "provider": provider,
                "alias": alias_value,
                "error": str(e),
            },
        )
        client_error = safe_error_message(e)
        _task_error = client_error
        try:
            await archiver.on_run_error(client_error)
        except Exception:
            pass

        try:
            err_event = adapter.create_error_event(client_error)
            if err_event:
                await _archive_converted_sse(err_event)
        except Exception:
            pass

        return client_error
    finally:
        try:
            await archiver.on_run_finished()
        except Exception:
            pass

        # Persist captured CLI session ID for future provider-native resume
        if _captured_cli_session_id:
            try:
                task.cli_session_id = _captured_cli_session_id
                task.claude_session_id = _captured_cli_session_id
                task.execution_binding = task.to_execution_binding()
                storage.upsert_execution_binding(
                    session_id=session_id,
                    cli_session_id=_captured_cli_session_id,
                    provider=provider,
                    alias=alias_value,
                    exec_user=exec_user,
                    work_dir=work_dir or None,
                    source_type="task",
                    source_session_id=source_session_id,
                    task_id=task.id,
                    session_kind=binding_info["session_kind"],
                )
                if task_queue:
                    task_queue.update_task(task)
                    logger.info(
                        "Saved CLI session ID for task",
                        extra={
                            "task_id": task.id,
                            "session_id": session_id,
                            "cli_session_id": _captured_cli_session_id,
                            "provider": provider,
                        },
                    )
            except Exception as e:
                logger.warning(
                    "Failed to save CLI session ID for task",
                    extra={"task_id": task.id, "session_id": session_id, "error": str(e)},
                )

        # Send task completion notification only for terminal outcomes.
        if not _retry_requested:
            _has_notification = getattr(task, "response_url", None) or getattr(task, "notification_sink_type", None)
            if _has_notification:
                try:
                    from src.server.services.task_notifier import TaskNotifier
                    notifier = TaskNotifier()
                    task_succeeded = _task_error is None
                    notification_target = task.get_notification_target() if hasattr(task, "get_notification_target") else None
                    await notifier.notify_task_completion(
                        task_id=task.id,
                        session_id=session_id,
                        response_url=task.response_url,
                        callback_msg_id=getattr(task, "callback_msg_id", None),
                        callback_user=getattr(task, "callback_user", None),
                        success=task_succeeded,
                        error_message=_task_error if not task_succeeded else None,
                        source_session_id=getattr(task, "source_session_id", None),
                        notification_target=notification_target,
                    )
                except Exception as notify_err:
                    logger.warning(
                        "Failed to send task completion notification",
                        extra={"task_id": task.id, "session_id": session_id, "error": str(notify_err)},
                    )

        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        telemetry.set_gauge("task_execution.last_duration_ms", duration_ms)
        telemetry.set_gauge(
            "task_execution.last_status_code",
            float(202 if _retry_requested else (200 if _task_error is None else 500)),
        )
        telemetry.set_gauge("task_execution.last_retry_requested", 1.0 if _retry_requested else 0.0)


def _handle_ralph_loop(task, session_id: str, storage, task_queue) -> Optional[str]:
    """Check Ralph Loop keywords and decide whether to re-queue.

    Returns:
        ``None`` to continue normal flow, ``RALPH_LOOP_RETRY_SIGNAL``
        to re-queue, or explicit ``None`` (via ``return None``) on
        keyword match / max-iteration exhaustion.
    """
    if not getattr(task, 'loop_enabled', False):
        return None  # not a loop task — continue normal flow
    if task.loop_iteration >= task.loop_max_iterations:
        return None

    task.loop_iteration = (task.loop_iteration or 0) + 1
    keyword_found = False
    loop_keywords = getattr(task, 'loop_keywords', []) or []

    if loop_keywords:
        try:
            messages = storage.get_session_messages(session_id)
            assistant_msgs = [m for m in messages if m.role == "assistant"]
            if assistant_msgs:
                last_content = (assistant_msgs[-1].content or "").lower()
                for kw in loop_keywords:
                    if kw.lower() in last_content:
                        keyword_found = True
                        break
        except Exception as e:
            logger.warning(f"Ralph Loop keyword check failed for task {task.id}: {e}")

    task.loop_keyword_found = keyword_found
    if task_queue:
        task_queue.update_task(task)

    if keyword_found:
        telemetry.increment("task_execution.loop.keyword_found")
        record_sampled_event(
            "task_execution.loop.keyword_found",
            {
                "task_id": task.id,
                "session_id": session_id,
                "iteration": task.loop_iteration,
                "max_iterations": task.loop_max_iterations,
            },
        )
        logger.info(
            "Ralph Loop keyword found",
            extra={"task_id": task.id, "session_id": session_id, "iteration": task.loop_iteration},
        )
        return None  # keyword matched → success, stop iterating

    if task.loop_iteration >= task.loop_max_iterations:
        telemetry.increment("task_execution.loop.max_iterations")
        record_sampled_event(
            "task_execution.loop.max_iterations",
            {
                "task_id": task.id,
                "session_id": session_id,
                "iteration": task.loop_iteration,
                "max_iterations": task.loop_max_iterations,
            },
        )
        logger.info(
            "Ralph Loop max iterations reached",
            extra={"task_id": task.id, "session_id": session_id, "iteration": task.loop_iteration},
        )
        return None  # exhausted → treat as success

    telemetry.increment("task_execution.loop.retry_queued")
    record_sampled_event(
        "task_execution.loop.retry_queued",
        {
            "task_id": task.id,
            "session_id": session_id,
            "iteration": task.loop_iteration,
            "max_iterations": task.loop_max_iterations,
        },
    )
    logger.info(
        "Ralph Loop retry queued",
        extra={
            "task_id": task.id,
            "session_id": session_id,
            "iteration": task.loop_iteration,
            "max_iterations": task.loop_max_iterations,
        },
    )
    return RALPH_LOOP_RETRY_SIGNAL
