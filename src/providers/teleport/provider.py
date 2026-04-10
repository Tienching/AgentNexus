# -*- coding: utf-8 -*-
"""TeleportProvider — forwards execution requests to a remote agent-nexus endpoint.

Implements the BaseExecutor interface, translating local execution requests
into remote HTTP calls via the TeleportBridge.
"""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator

from ..base import BaseExecutor, ExecutorConfig, RequestContext
from ...server.logger import get_logger
from ...server.services.teleport_bridge import TeleportBridge

logger = get_logger(__name__)


class TeleportProvider(BaseExecutor):
    """Provider that forwards CLI execution requests to a remote environment.

    Uses TeleportBridge for session management and HTTP transport.
    The remote endpoint must expose a compatible ``/api/chat`` endpoint.
    """

    def __init__(
        self,
        config: ExecutorConfig | None = None,
        session_id: str | None = None,
    ):
        super().__init__(config)
        self._session_id = session_id
        self._bridge = TeleportBridge.get_instance()

    def set_session(self, session_id: str) -> None:
        """Set the teleport session to use for execution."""
        self._session_id = session_id

    async def execute(
        self,
        context: RequestContext,
        output_format: str = "raw",
    ) -> AsyncGenerator[str, None]:
        """Execute a request on the remote environment.

        Streams output from the remote endpoint, yielding lines in the
        requested output format.
        """
        if not self._session_id:
            yield json.dumps({"error": "No teleport session configured"}) + "\n"
            return

        session = self._bridge.get_session(self._session_id)
        if not session:
            yield json.dumps({"error": f"Session not found: {self._session_id}"}) + "\n"
            return

        if session.status != "connected":
            yield json.dumps({"error": f"Session not connected (status={session.status})"}) + "\n"
            return

        # Forward the execution request through the bridge
        task_metadata = {
            "user": context.user,
            "session_id": context.session_id,
            "cwd": context.cwd,
            "model": context.model,
            "alias": context.alias,
        }

        try:
            async for chunk in self._bridge.execute_remote_streaming(
                session_id=self._session_id,
                task=context.content,
                task_metadata=task_metadata,
            ):
                if output_format == "legacy":
                    yield f"event: delta\ndata: {json.dumps({'text': chunk})}\n\n"
                else:
                    yield chunk + "\n"
        except Exception as exc:
            logger.error(f"Teleport execution error: {exc}", exc_info=True)
            error_payload = {"error": str(exc), "session_id": self._session_id}
            yield json.dumps(error_payload) + "\n"

    def _build_command(self, context: RequestContext) -> list[str]:
        """Not used — remote execution does not build local commands."""
        return []
