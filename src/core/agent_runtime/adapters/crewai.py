# -*- coding: utf-8 -*-
"""CrewAI adapter."""

from __future__ import annotations

from src.core.agent_runtime.adapters.base import AgentFrameworkAdapter, AdapterRequest, AdapterResponse


class CrewAIAdapter(AgentFrameworkAdapter):
    name = "crewai"

    def available(self) -> bool:
        return True

    def run(self, request: AdapterRequest) -> AdapterResponse:
        return AdapterResponse(
            output=request.prompt,
            success=True,
            metadata={"adapter": self.name, "mode": "passthrough"},
        )
