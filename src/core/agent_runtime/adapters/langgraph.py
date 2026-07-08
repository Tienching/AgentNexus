# -*- coding: utf-8 -*-
"""LangGraph adapter."""

from __future__ import annotations

from src.core.agent_runtime.adapters.base import AgentFrameworkAdapter, AdapterRequest, AdapterResponse


class LangGraphAdapter(AgentFrameworkAdapter):
    name = "langgraph"

    def available(self) -> bool:
        return True

    def run(self, request: AdapterRequest) -> AdapterResponse:
        return AdapterResponse(
            output=request.prompt,
            success=True,
            metadata={"adapter": self.name, "mode": "passthrough"},
        )
