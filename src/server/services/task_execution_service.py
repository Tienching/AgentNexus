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
import uuid
from typing import Optional, TYPE_CHECKING

from src.providers.dispatcher import normalize_provider, create_executor, create_adapter
from src.server.logger import get_logger
from src.server.utils.ids import gen_run_id

if TYPE_CHECKING:
    from src.server.models import Task

logger = get_logger(__name__)

# Sentinel returned to the executor to signal a Ralph Loop re-queue.
RALPH_LOOP_RETRY_SIGNAL = "__RALPH_LOOP_RETRY__"


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

    exec_user = task.exec_user or "ubuntu"
    logger.info(f"task_handler: task.session_id={task.session_id!r}, task.id={task.id}")
    session_id = task.session_id or f"task_{task.id}"
    logger.info(f"task_handler: using session_id={session_id}")
    run_id = gen_run_id()

    logger.info(f"Executing task {task.id} for exec_user {exec_user}: {task.description[:50]}...")

    # ── Provider dispatch ─────────────────────────────────────────
    provider = normalize_provider(getattr(task, "provider", None))
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

    alias_value = (getattr(task, "alias", None) or provider)
    model_value = (getattr(task, "model", None) or "").strip() or None

    cli_session_id = (
        getattr(task, "cli_session_id", None)
        or getattr(task, "claude_session_id", None)
        or None
    )

    # ── Build RequestModel ────────────────────────────────────────
    request = RequestModel(
        content=user_prompt,
        user=task.project_id or "task_executor",
        session_id=session_id,
        msg_id=run_id,
        cwd=task.workspace or "",
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
    )

    storage = get_session_storage()

    # Store task_id in session meta
    try:
        key = f"session:{session_id}:meta"
        storage._redis.hset(key, "task_id", task.id)
    except Exception as e:
        logger.warning(f"Failed to set task_id in session meta: {e}")

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

    try:
        await archiver.on_run_started(initial_messages)

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
                        logger.info(f"Captured CLI session ID for task {task.id}: {_sid}")

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
            return result

        logger.info(f"Task {task.id} completed successfully")
        _task_error = None
        return None

    except asyncio.CancelledError:
        logger.warning(f"Task {task.id} was cancelled")
        raise
    except Exception as e:
        logger.error(f"Task {task.id} failed: {e}", exc_info=True)
        _task_error = str(e)
        try:
            await archiver.on_run_error(str(e))
        except Exception:
            pass

        try:
            err_event = adapter.create_error_event(str(e))
            if err_event:
                await _archive_converted_sse(err_event)
        except Exception:
            pass

        return str(e)
    finally:
        try:
            await archiver.on_run_finished()
        except Exception:
            pass

        # Persist captured CLI session ID for future --resume
        if _captured_cli_session_id:
            try:
                task.cli_session_id = _captured_cli_session_id
                task.claude_session_id = _captured_cli_session_id
                if task_queue:
                    task_queue.update_task(task)
                    logger.info(f"Saved cli_session_id={_captured_cli_session_id} for task {task.id}")
            except Exception as e:
                logger.warning(f"Failed to save cli_session_id for task {task.id}: {e}")

        # Send task completion notification
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
                logger.warning(f"Failed to send task completion notification: {notify_err}")


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
        logger.info(f"Ralph Loop: keyword found for task {task.id} at iteration {task.loop_iteration}")
        return None  # keyword matched → success, stop iterating

    if task.loop_iteration >= task.loop_max_iterations:
        logger.info(f"Ralph Loop: max iterations ({task.loop_max_iterations}) reached for task {task.id}")
        return None  # exhausted → treat as success

    logger.info(f"Ralph Loop: keyword NOT found for task {task.id}, iteration {task.loop_iteration}/{task.loop_max_iterations}, re-queuing")
    return RALPH_LOOP_RETRY_SIGNAL
