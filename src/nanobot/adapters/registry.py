# -*- coding: utf-8 -*-
"""Adapter registry for framework-agnostic execution."""

from __future__ import annotations

from typing import Dict, List, Optional

from src.nanobot.adapters.base import AgentFrameworkAdapter, AdapterRequest, AdapterResponse


class AdapterRegistry:
    def __init__(self):
        self._adapters: Dict[str, AgentFrameworkAdapter] = {}

    def register(self, adapter: AgentFrameworkAdapter) -> None:
        self._adapters[adapter.name] = adapter

    def get(self, name: str) -> Optional[AgentFrameworkAdapter]:
        return self._adapters.get(name)

    def list_names(self, only_available: bool = False) -> List[str]:
        names = []
        for name, adapter in self._adapters.items():
            if only_available and not adapter.available():
                continue
            names.append(name)
        return sorted(names)

    def run(self, name: str, request: AdapterRequest) -> AdapterResponse:
        adapter = self.get(name)
        if adapter is None:
            return AdapterResponse(output="", success=False, error=f"Adapter not found: {name}")
        if not adapter.available():
            return AdapterResponse(output="", success=False, error=f"Adapter unavailable: {name}")
        return adapter.run(request)


_registry: Optional[AdapterRegistry] = None


def get_adapter_registry() -> AdapterRegistry:
    global _registry
    if _registry is None:
        _registry = AdapterRegistry()
    return _registry
