# -*- coding: utf-8 -*-
"""Claude SDK adapter."""

from __future__ import annotations

from src.nanobot.adapters.base import AgentFrameworkAdapter, AdapterRequest, AdapterResponse


class ClaudeSDKAdapter(AgentFrameworkAdapter):
    name = "claude-sdk"

    def available(self) -> bool:
        return True

    def run(self, request: AdapterRequest) -> AdapterResponse:
        return AdapterResponse(
            output=request.prompt,
            success=True,
            metadata={"adapter": self.name, "mode": "passthrough"},
        )
