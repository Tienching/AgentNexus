# -*- coding: utf-8 -*-
"""AutoGen adapter."""

from __future__ import annotations

from src.nanobot.adapters.base import AgentFrameworkAdapter, AdapterRequest, AdapterResponse


class AutoGenAdapter(AgentFrameworkAdapter):
    name = "autogen"

    def available(self) -> bool:
        return True

    def run(self, request: AdapterRequest) -> AdapterResponse:
        return AdapterResponse(
            output=request.prompt,
            success=True,
            metadata={"adapter": self.name, "mode": "passthrough"},
        )
