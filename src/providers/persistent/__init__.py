# -*- coding: utf-8 -*-
"""Persistent CLI Process — long-lived subprocess with stdin/stdout pipes.

Replaces the per-request subprocess model for sessions that benefit from
persistent context.  The CLI process stays alive across multiple user
messages, using ``--input-format stream-json`` / ``--output-format stream-json``
to communicate over stdin/stdout pipes.

Architecture
~~~~~~~~~~~~
::

    PersistentProcessManager (singleton per CLIExecutor)
        └── PersistentProcess (one per session)
                ├── stdin  ← send_message() writes JSON lines
                ├── stdout → stream_output() yields JSON lines
                └── CompletionDetector determines when a turn is done

Usage from CLIExecutor::

    manager = PersistentProcessManager(config)
    proc = await manager.get_or_create(session_id, exec_user, ...)
    await proc.send_message(content)
    async for line in proc.stream_output():
        yield line  # JSON events compatible with _process_stream()
"""

from .process_manager import PersistentProcessManager, PersistentProcess
from .completion_detector import CompletionDetector, CompletionStatus

__all__ = [
    "PersistentProcessManager",
    "PersistentProcess",
    "CompletionDetector",
    "CompletionStatus",
]
