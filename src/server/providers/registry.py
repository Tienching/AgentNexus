# -*- coding: utf-8 -*-
"""Provider registry and resolution for the API layer.

Core provider implementations live in `src.providers.runtime`.
This module handles HTTP-specific provider resolution (query/body/session lookup).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol

from fastapi import Request

from ..logger import get_logger
from ..adapters import ProtocolType
from ..services.session_storage import get_session_storage

# Single source of truth for provider registry.
from src.providers.runtime.registry import get_provider_registry as get_runtime_provider_registry

logger = get_logger(__name__)


# ============ Base Types ============

class Executor(Protocol):
    """Protocol for command executors"""
    async def execute(self, request_model, exec_user: str, output_format: str = "raw"):
        ...


class Provider(Protocol):
    """Protocol for providers"""
    name: str

    def get_executor(self) -> Executor:
        ...

    def get_adapter(self, protocol: ProtocolType):
        ...


@dataclass(frozen=True)
class ProviderResolution:
    """Resolved provider information.

    - `name`: the requested/provider label (e.g., from query/body/session meta)
    - `backend`: which backend implementation is used (gemini -> gemini, else claude)
    """

    name: str
    backend: str


class ProviderRegistry:
    """HTTP-facing provider resolution + provider list.

    Notes:
    - The canonical provider registry lives in `src.providers.runtime`.
    - This module keeps HTTP-specific parsing (query/body/forwardedProps + session meta lookup).
    - Backward-compat: unknown provider names still execute on Claude backend.
    """

    def __init__(self):
        self._rt = get_runtime_provider_registry()

    def list_providers(self) -> list[str]:
        return self._rt.list_providers()

    def resolve_provider(self, request: Request, body_dict: Dict[str, Any]) -> ProviderResolution:
        """Resolve provider label + backend.

        Mirrors the historic behavior in `StreamHandler._get_provider()`.
        Priority: X-Provider header > query param > body > forwardedProps > session meta
        """

        explicit_provider = ""
        
        # 1. Check X-Provider header first
        try:
            explicit_provider = request.headers.get("X-Provider", "") or request.headers.get("x-provider", "")
        except Exception:
            pass
        
        # 2. Check query params
        if not explicit_provider:
            try:
                explicit_provider = request.query_params.get("provider", "")
            except Exception:
                explicit_provider = ""

        # 3. Check body
        if not explicit_provider and isinstance(body_dict, dict):
            explicit_provider = body_dict.get("provider", "")
            if not explicit_provider:
                forwarded = body_dict.get("forwardedProps")
                if isinstance(forwarded, dict):
                    explicit_provider = forwarded.get("provider", "")

        # 4. Check session meta
        session_provider = ""
        if not explicit_provider and isinstance(body_dict, dict):
            session_id = body_dict.get("threadId") or body_dict.get("session_id") or body_dict.get("sessionId")
            if session_id:
                try:
                    storage = get_session_storage()
                    meta = storage.get_session_meta(session_id)
                    if meta and getattr(meta, "provider", None):
                        session_provider = meta.provider
                except Exception:
                    pass

        explicit_provider = (explicit_provider or "").strip().lower()
        session_provider = (session_provider or "").strip().lower()

        resolved = self._rt.resolve_provider(
            explicit=explicit_provider or None,
            session_meta={"provider": session_provider} if session_provider else None,
        )

        name = resolved.provider_name if resolved.provider_name else "nanobot"
        # Map backend based on provider name
        if name == "nanobot":
            backend = "nanobot"
        elif name == "gemini":
            backend = "gemini"
        elif name == "codex":
            backend = "codex"
        elif name == "codebuddy":
            backend = "codebuddy"
        elif name == "claude":
            backend = "claude"
        else:
            backend = "nanobot"
        return ProviderResolution(name=name, backend=backend)


_registry: Optional[ProviderRegistry] = None


def get_provider_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
    return _registry
