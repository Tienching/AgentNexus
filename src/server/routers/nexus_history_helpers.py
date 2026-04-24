# -*- coding: utf-8 -*-
"""Shared helpers for the Nexus history router."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from ..config import settings
from ..logger import get_logger
from ..models import (
    MessageStatus,
    SessionMessagesResponse,
    SessionMeta,
    SessionStatus,
    StoredMessage,
)
from ..services.app_container import get_app_container

from src.runtime.history import HistoryService
from src.runtime.history.alias_resolution import (
    PROVIDER_CONFIG_DIRS as _SHARED_PROVIDER_CONFIG_DIRS,
    build_alias_config_map as _shared_build_alias_config_map,
    custom_path_belongs_to_user_home as _shared_custom_path_belongs_to_user_home,
    infer_base_provider as _shared_infer_base_provider,
    resolve_history_user_homes as _shared_resolve_history_user_homes,
    resolve_tilde as _shared_resolve_tilde,
)

logger = get_logger("src.server.routers.nexus_history")

PROVIDER_CONFIG_DIRS = dict(_SHARED_PROVIDER_CONFIG_DIRS)
PROVIDER_PARSER_MAP = {
    "claude": "claude",
    "codebuddy": "codebuddy",
    "codex": "codex",
    "gemini": "gemini",
}

_history_observability = {
    "read_failures": 0,
    "compat_hits": 0,
    "read_failures_by_kind": {},
    "compat_hits_by_kind": {},
    "last_read_failure": None,
    "last_compat_hit": None,
}


def get_history_service() -> HistoryService:
    """Get the app-scoped HistoryService."""
    return get_app_container().history_service()


def record_history_observability(
    kind: str,
    *,
    failure: bool,
    provider: Optional[str] = None,
    session_id: Optional[str] = None,
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    bucket_key = "read_failures_by_kind" if failure else "compat_hits_by_kind"
    total_key = "read_failures" if failure else "compat_hits"
    last_key = "last_read_failure" if failure else "last_compat_hit"

    _history_observability[total_key] = int(_history_observability.get(total_key, 0) or 0) + 1
    bucket = _history_observability.setdefault(bucket_key, {})
    bucket[kind] = int(bucket.get(kind, 0) or 0) + 1

    payload = {
        "kind": kind,
        "provider": provider,
        "session_id": session_id,
        "detail": detail or {},
        "timestamp": int(time.time() * 1000),
    }
    _history_observability[last_key] = payload

    if failure:
        logger.warning("History read failure: %s", payload)
    else:
        logger.info("History compat hit: %s", payload)



def record_history_read_failure(
    kind: str,
    *,
    provider: Optional[str] = None,
    session_id: Optional[str] = None,
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    record_history_observability(
        kind,
        failure=True,
        provider=provider,
        session_id=session_id,
        detail=detail,
    )



def record_history_compat_hit(
    kind: str,
    *,
    provider: Optional[str] = None,
    session_id: Optional[str] = None,
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    record_history_observability(
        kind,
        failure=False,
        provider=provider,
        session_id=session_id,
        detail=detail,
    )



def get_history_observability_snapshot() -> Dict[str, Any]:
    """Return a shallow copy of the history observability state."""
    return {
        "read_failures": int(_history_observability.get("read_failures", 0) or 0),
        "compat_hits": int(_history_observability.get("compat_hits", 0) or 0),
        "read_failures_by_kind": dict(_history_observability.get("read_failures_by_kind", {}) or {}),
        "compat_hits_by_kind": dict(_history_observability.get("compat_hits_by_kind", {}) or {}),
        "last_read_failure": _history_observability.get("last_read_failure"),
        "last_compat_hit": _history_observability.get("last_compat_hit"),
    }



def resolve_tilde(path_str: str, user_home: Path) -> Path:
    """Resolve ~ or ~/ to the target user home directory."""
    return _shared_resolve_tilde(path_str, user_home)



def infer_base_provider(alias_name: str) -> Optional[str]:
    return _shared_infer_base_provider(alias_name)



def custom_path_belongs_to_user_home(path_obj: Path, user_home: Path) -> bool:
    """Whether a custom config path should apply to the current user home."""
    return _shared_custom_path_belongs_to_user_home(path_obj, user_home)



def resolve_history_user_homes(exec_user: str) -> List[Path]:
    """Resolve target user home directories for history scanning."""
    return _shared_resolve_history_user_homes(
        exec_user=exec_user,
        user_home_base=settings.user_home_base or "/home",
        fallback_exec_user=settings.exec_user or "ubuntu",
    )



def build_alias_config_map(
    user_home: Path,
    custom_paths_str: str,
    provider_filter: Optional[str] = None,
) -> Dict[str, Path]:
    """Build alias -> config_path mapping from defaults + custom paths."""
    try:
        from src.runtime.stores.alias_registry import get_alias_registry

        registry_map = get_alias_registry().list_all() or {}
    except Exception:
        registry_map = {}

    return _shared_build_alias_config_map(
        user_home=user_home,
        provider_filter=provider_filter,
        alias_registry_map=registry_map,
        custom_paths_str=custom_paths_str,
    )



def resolve_nexus_workspace_path(workspace: Optional[str] = None) -> Path:
    """Resolve Nexus workspace path used by persistent memory files."""
    candidate = (workspace or "").strip()
    if candidate:
        return Path(candidate).expanduser().resolve()

    configured = (
        getattr(settings, "nexus_workspace", None)
        or getattr(settings, "nanobot_workspace", "")
        or ""
    ).strip()
    if configured:
        return Path(configured).expanduser().resolve()

    return (Path.home() / "Projects").resolve()



def resolve_base_provider(provider_or_alias: str) -> str:
    p = (provider_or_alias or "").strip().lower()
    if p in PROVIDER_CONFIG_DIRS:
        return p
    for base in PROVIDER_CONFIG_DIRS:
        if p.startswith(base):
            return base
    return p or "claude"



def resolve_history_candidate_configs(
    provider: str,
    *,
    exec_user: str = "",
    config_path: Optional[str] = None,
) -> List[Path]:
    """Resolve candidate history config directories for a provider or alias."""
    user_homes = resolve_history_user_homes(exec_user)
    candidate_configs: List[Path] = []

    if config_path:
        for user_home in user_homes:
            resolved = resolve_tilde(config_path, user_home)
            if resolved.is_absolute():
                candidate_configs.append(resolved)
    else:
        if provider in PROVIDER_CONFIG_DIRS:
            for user_home in user_homes:
                candidate_configs.append(user_home / PROVIDER_CONFIG_DIRS[provider])
        else:
            is_alias = any(provider.startswith(pname) for pname in PROVIDER_CONFIG_DIRS)
            if not is_alias:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown provider '{provider}'. Provide config_path for custom aliases.",
                )
            for user_home in user_homes:
                candidate_configs.append(user_home / f".{provider}")

    unique_candidates: List[Path] = []
    seen = set()
    for candidate in candidate_configs:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique_candidates.append(candidate)
    return unique_candidates



def resolve_exec_user_home(exec_user: str = "") -> Tuple[str, Path]:
    """Resolve the effective exec user and their home directory."""
    user = exec_user or settings.exec_user or "ubuntu"
    home_base = settings.user_home_base or "/home"
    return user, Path(home_base) / user



def resolve_provider_config_path(provider: str, *, user_home: Path) -> Path:
    """Resolve the history config directory for a provider or alias."""
    if provider in PROVIDER_CONFIG_DIRS:
        return user_home / PROVIDER_CONFIG_DIRS[provider]
    return user_home / f".{provider}"



def build_bootstrap_context(detail: SessionMessagesResponse, mode: str = "full") -> str:
    """Build bootstrap context text from history messages."""
    messages = detail.messages or []
    if not messages:
        return "(历史会话没有可用消息)"

    effective_mode = (mode or "full").strip().lower()
    if effective_mode == "summary":
        effective_mode = "windowed"
    if effective_mode not in ("full", "windowed"):
        effective_mode = "full"

    if effective_mode == "windowed":
        messages = messages[-50:]

    lines: List[str] = []
    for message in messages:
        role = "用户" if message.role == "user" else "助手"
        content = (message.content or "").strip()
        if not content:
            continue
        if effective_mode == "windowed" and len(content) > 800:
            content = content[:800] + "…(截断)"
        lines.append(f"[{role}] {content}")

    return "\n\n".join(lines) if lines else "(历史会话没有可用消息)"



def infer_history_project_path(detail: SessionMessagesResponse) -> str:
    """Infer the workspace path from history session metadata."""
    return (
        getattr(detail.session, "exec_dir", None)
        or getattr(detail.session, "work_dir", None)
        or ""
    ).strip()



def import_history_detail(
    storage: Any,
    session_id: str,
    detail: SessionMessagesResponse,
    *,
    clear_existing: bool = False,
) -> Tuple[int, int]:
    """Copy parsed history messages and tool calls into runtime storage."""
    if clear_existing:
        storage.clear_session_messages(session_id)
        storage.clear_session_tool_calls(session_id)

    message_count = 0
    for message in detail.messages or []:
        role = message.role if message.role in ("user", "assistant", "system") else "assistant"
        imported = StoredMessage(
            id=f"hist-{message.id}",
            role=role,
            content=message.content or "",
            status=MessageStatus.COMPLETE,
            tool_call_ids=message.tool_call_ids,
            content_segments=message.content_segments,
        )
        storage.add_session_message(session_id, imported)
        message_count += 1

    tool_call_count = 0
    for tool_call in detail.tool_calls or []:
        tool_call_copy = tool_call.model_copy(deep=True)
        tool_call_copy.id = f"hist-{tool_call.id}"
        if tool_call_copy.parent_message_id:
            tool_call_copy.parent_message_id = f"hist-{tool_call_copy.parent_message_id}"
        storage.save_tool_call(session_id, tool_call_copy)
        tool_call_count += 1

    return message_count, tool_call_count



def build_runtime_session_meta(
    runtime_session_id: str,
    detail: SessionMessagesResponse,
    *,
    user: str,
    base_provider: str,
    provider_alias: str,
    source_session_id: str,
    project_path: str,
    now_ms: Optional[int] = None,
) -> SessionMeta:
    """Build runtime metadata for a resumed history session."""
    created_ms = int(now_ms or time.time() * 1000)
    title = (detail.session.title if detail.session else None) or f"History: {source_session_id}"
    return SessionMeta(
        id=runtime_session_id,
        thread_id=runtime_session_id,
        run_id=None,
        title=title,
        username=user,
        exec_user=user,
        provider=base_provider,
        alias=provider_alias,
        source="history",
        source_session_id=source_session_id,
        session_kind="chat",
        created_at=created_ms,
        updated_at=created_ms,
        message_count=0,
        status=SessionStatus.IDLE,
        exec_dir=project_path,
    )
