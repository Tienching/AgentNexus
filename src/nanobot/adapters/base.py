# -*- coding: utf-8 -*-
"""Adapter base abstractions for multi-framework orchestration."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class AdapterRequest:
    prompt: str
    context: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AdapterResponse:
    output: str
    success: bool = True
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class AgentFrameworkAdapter(ABC):
    """Abstract adapter interface for external agent frameworks."""

    name: str = "base"

    @abstractmethod
    def available(self) -> bool:
        """Return True if the target framework runtime is available."""

    @abstractmethod
    def run(self, request: AdapterRequest) -> AdapterResponse:
        """Execute one adapter request."""
