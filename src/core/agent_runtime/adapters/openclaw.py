# -*- coding: utf-8 -*-
"""OpenClaw adapter."""

from __future__ import annotations

from src.core.agent_runtime.adapters.base import AgentFrameworkAdapter, AdapterRequest, AdapterResponse


class OpenClawAdapter(AgentFrameworkAdapter):
    name = "openclaw"

    def available(self) -> bool:
        return True

    def run(self, request: AdapterRequest) -> AdapterResponse:
        # Integration stub for unified adapter layer.
        return AdapterResponse(
            output=request.prompt,
            success=True,
            metadata={"adapter": self.name, "mode": "passthrough"},
        )
