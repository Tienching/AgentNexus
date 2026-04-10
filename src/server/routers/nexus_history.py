# -*- coding: utf-8 -*-
"""History API Router for NexusHub.

Provides REST API endpoints for reading native CLI session history files
from Claude Code, Codex, CodeBuddy, and Gemini providers.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..config import settings
from ..logger import get_logger
from ..models import (
    SessionListResponse,
    SessionMessagesResponse,
    SessionMeta,
    SessionStatus,
    StoredMessage,
    MessageStatus,
)
from ..services.session_storage import get_session_storage
from .nexus_auth import verify_nexus_auth

from src.runtime.history import HistoryService
from src.runtime.history.claude_parser import ClaudeHistoryParser
from src.runtime.history.codex_parser import CodexHistoryParser
from src.runtime.history.codebuddy_parser import CodeBuddyHistoryParser
from src.runtime.history.gemini_parser import GeminiHistoryParser
from src.nanobot.agent.memory import MemoryStore

logger = get_logger(__name__)

# Default provider -> config directory name mapping (same as Skills API)
_PROVIDER_CONFIG_DIRS = {
    "claude": ".claude",
    "codebuddy": ".codebuddy",
    "codex": ".codex",
    "gemini": ".gemini",
}

# Provider name -> which parser handles it
_PROVIDER_PARSER_MAP = {
    "claude": "claude",
    "codebuddy": "codebuddy",
    "codex": "codex",
    "gemini": "gemini",
}

# Singleton service
_history_service: Optional[HistoryService] = None


def _get_history_service() -> HistoryService:
    """Get or create the singleton HistoryService."""
    global _history_service
    if _history_service is None:
        _history_service = HistoryService()
        _history_service.register_parser(ClaudeHistoryParser())
        _history_service.register_parser(CodexHistoryParser())
        _history_service.register_parser(CodeBuddyHistoryParser())
        _history_service.register_parser(GeminiHistoryParser())
    return _history_service


router = APIRouter(
    prefix="/api/nexus/history",
    tags=["nexus-history"],
    dependencies=[Depends(verify_nexus_auth)],
)


def _resolve_tilde(path_str: str, user_home: Path) -> Path:
    """Resolve ~ or ~/ to the target user home directory."""
    if path_str.startswith("~/") or path_str == "~":
        return user_home / path_str[2:] if len(path_str) > 2 else user_home
    return Path(path_str)


def _infer_base_provider(alias_name: str) -> Optional[str]:
    alias = (alias_name or "").strip().lower()
    if not alias:
        return None
    if alias in _PROVIDER_PARSER_MAP:
        return alias
    for provider_name in _PROVIDER_PARSER_MAP:
        if alias.startswith(provider_name):
            return provider_name
    return None


def _custom_path_belongs_to_user_home(path_obj: Path, user_home: Path) -> bool:
    """Whether a custom config path should apply to the current user home.

    - Paths under /home/<same-user>/... are allowed.
    - Paths under /home/<other-user>/... are ignored to avoid cross-user pollution.
    - Non-/home absolute paths are kept as global/shared paths.
    """
    try:
        resolved = path_obj.resolve()
    except Exception:
        resolved = path_obj

    parts = resolved.parts
    if len(parts) >= 3 and parts[0] == "/" and parts[1] == "home":
        return parts[2] == user_home.name
    return True


def _resolve_history_user_homes(exec_user: str) -> List[Path]:
    """Resolve target user home directories.

    - When ``exec_user`` is specified, only that user's home is returned.
    - When empty (All Users), returns all directories under ``/home`` plus the
      configured default user home as fallback.
    """
    home_base = settings.user_home_base or "/home"
    base_home = Path(home_base)
    chosen_user = (exec_user or "").strip()
    if chosen_user:
        return [base_home / chosen_user]

    homes: List[Path] = []
    if base_home.is_dir():
        try:
            for entry in sorted(base_home.iterdir()):
                if entry.is_dir():
                    homes.append(entry)
        except Exception:
            pass

    fallback_user = (settings.exec_user or "ubuntu").strip() or "ubuntu"
    fallback_home = base_home / fallback_user
    if fallback_home not in homes:
        homes.append(fallback_home)

    seen = set()
    ordered: List[Path] = []
    for home in homes:
        key = str(home)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(home)
    return ordered


def _build_alias_config_map(
    user_home: Path,
    custom_paths_str: str,
    provider_filter: Optional[str] = None,
) -> Dict[str, Path]:
    """Build alias -> config_path mapping from defaults + custom_paths.

    Also auto-discovers alias directories (e.g. ``~/.claude-internal``) using
    alias registry and home-directory scanning, so history API can work even
    when frontend localStorage has no alias config.
    """
    normalized_filter = (provider_filter or "").strip().lower() or None
    alias_map: Dict[str, Path] = {}

    # Add default providers
    for provider, config_dir in _PROVIDER_CONFIG_DIRS.items():
        if normalized_filter and provider != normalized_filter:
            continue
        alias_map[provider] = user_home / config_dir

    # Add aliases from alias registry when corresponding config dir exists
    try:
        from src.runtime.stores.alias_registry import get_alias_registry

        registry_map = get_alias_registry().list_all() or {}
    except Exception:
        registry_map = {}

    for alias_name_raw, provider_raw in registry_map.items():
        alias_name = (alias_name_raw or "").strip().lower()
        provider_name = (provider_raw or "").strip().lower()
        if not alias_name:
            continue
        if normalized_filter and alias_name != normalized_filter and provider_name != normalized_filter:
            continue

        config_dir = user_home / f".{alias_name}"
        try:
            if config_dir.exists():
                alias_map[alias_name] = config_dir
        except OSError:
            continue

    # Parse and add custom alias paths (higher priority)
    if custom_paths_str:
        try:
            custom_paths: Dict[str, str] = json.loads(custom_paths_str)
        except (json.JSONDecodeError, TypeError):
            custom_paths = {}

        for alias_name_raw, path_str in custom_paths.items():
            alias_name = (alias_name_raw or "").strip().lower()
            if not alias_name:
                continue

            base_provider = _infer_base_provider(alias_name)
            if normalized_filter and alias_name != normalized_filter and base_provider != normalized_filter:
                continue

            resolved = _resolve_tilde(path_str, user_home)
            if resolved.is_absolute():
                if _custom_path_belongs_to_user_home(resolved, user_home):
                    alias_map[alias_name] = resolved
                else:
                    logger.debug(
                        "Skipping cross-user custom path for alias '%s': %s (current home: %s)",
                        alias_name,
                        resolved,
                        user_home,
                    )
            else:
                logger.warning("Skipping non-absolute path for alias '%s': %s", alias_name, path_str)

    # Fallback scan: auto-detect hidden provider-family alias dirs in user home
    try:
        for entry in user_home.iterdir():
            if not entry.is_dir() or not entry.name.startswith("."):
                continue
            alias_name = entry.name[1:].strip().lower()
            if not alias_name or alias_name in alias_map:
                continue
            base_provider = _infer_base_provider(alias_name)
            if not base_provider:
                continue
            if normalized_filter and alias_name != normalized_filter and base_provider != normalized_filter:
                continue
            alias_map[alias_name] = entry
    except Exception:
        pass

    return alias_map


def _resolve_nanobot_workspace_path(workspace: Optional[str] = None) -> Path:
    """Resolve nanobot workspace path used by persistent memory files."""
    candidate = (workspace or "").strip()
    if candidate:
        return Path(candidate).expanduser().resolve()

    configured = (settings.nanobot_workspace or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()

    return (Path.home() / "Projects").resolve()


@router.get("/projects")
async def list_history_projects(
    exec_user: str = Query(default="", description="Exec user for home directory resolution"),
    custom_paths: str = Query(default="", description="JSON-encoded dict of alias->configPath"),
    provider: Optional[str] = Query(default=None, description="Filter by provider"),
):
    """Discover all available project paths from local CLI history files.

    Scans Claude, CodeBuddy, Codex, and Gemini config directories to find
    all project workspaces that have history sessions.

    Returns a list of projects, each with:
    - path: The project workspace path
    - providers: List of providers that have sessions for this project
    - total_sessions: Total session count across all providers
    - last_active: Most recent session timestamp (ms)
    """
    service = _get_history_service()
    user_homes = _resolve_history_user_homes(exec_user)

    merged_by_path: Dict[str, Dict[str, Any]] = {}
    for user_home in user_homes:
        alias_map = _build_alias_config_map(user_home, custom_paths, provider)
        if not alias_map:
            continue

        entries = await service.list_projects(
            alias_config_map=alias_map,
            provider_filter=provider,
        )
        for entry in entries or []:
            path = entry.get("path")
            if not path:
                continue
            bucket = merged_by_path.setdefault(path, {
                "path": path,
                "providers": [],
                "total_sessions": 0,
                "last_active": 0,
            })

            # Merge providers by (provider, alias)
            provider_counter: Dict[tuple, int] = {
                (p.get("provider"), p.get("alias")): int(p.get("session_count", 0) or 0)
                for p in bucket.get("providers", [])
            }
            for p in entry.get("providers", []) or []:
                key = (p.get("provider"), p.get("alias"))
                provider_counter[key] = provider_counter.get(key, 0) + int(p.get("session_count", 0) or 0)
            bucket["providers"] = [
                {"provider": k[0], "alias": k[1], "session_count": v}
                for k, v in provider_counter.items()
            ]

            bucket["total_sessions"] = sum(p["session_count"] for p in bucket["providers"])
            bucket["last_active"] = max(
                int(bucket.get("last_active", 0) or 0),
                int(entry.get("last_active", 0) or 0),
            )
            if entry.get("gemini_hash"):
                bucket["gemini_hash"] = entry.get("gemini_hash")

    result = sorted(merged_by_path.values(), key=lambda x: int(x.get("last_active", 0) or 0), reverse=True)
    return result


@router.get("/sessions", response_model=SessionListResponse)
async def list_history_sessions(
    project_path: str = Query(..., description="Project workspace path (required, e.g. /home/bob/myproject)"),
    exec_user: str = Query(default="", description="Exec user for home directory resolution"),
    custom_paths: str = Query(default="", description="JSON-encoded dict of alias->configPath"),
    provider: Optional[str] = Query(default=None, description="Filter by provider (claude/codex/codebuddy/gemini)"),
    search: Optional[str] = Query(default=None, description="Search text for session title"),
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Page size"),
):
    """List local history sessions for a specific project workspace.

    This endpoint reads native CLI session files from the local filesystem.
    It does NOT access Redis — runtime sessions use a separate endpoint.

    Required parameter:
    - project_path: The workspace directory path (inplace cwd)

    Optional parameters:
    - custom_paths: JSON dict mapping alias names to their config directories
      e.g. {"claude-internal":"~/.claude-internal","codex-internal":"~/.codex-internal"}
    """
    if not project_path or not project_path.strip():
        raise HTTPException(status_code=400, detail="project_path is required")

    project_path = project_path.strip()
    user_homes = _resolve_history_user_homes(exec_user)

    # If project_path is a /home/<user>/... path, prefer that user first in All Users mode.
    project_owner_home: Optional[Path] = None
    try:
        resolved_project = Path(project_path).resolve()
        if str(resolved_project).startswith("/home/"):
            parts = resolved_project.parts
            if len(parts) >= 3:
                project_owner_home = Path("/home") / parts[2]
    except (ValueError, OSError):
        resolved_project = Path(project_path)

    if project_owner_home and project_owner_home in user_homes:
        user_homes = [project_owner_home] + [h for h in user_homes if h != project_owner_home]

    service = _get_history_service()

    # Aggregate sessions across resolved user homes, then paginate globally.
    merged: Dict[str, SessionMeta] = {}
    for user_home in user_homes:
        alias_map = _build_alias_config_map(user_home, custom_paths, provider)
        if not alias_map:
            continue

        try:
            part = await service.list_all_sessions(
                user_home=user_home,
                project_path=project_path,
                alias_config_map=alias_map,
                provider_filter=provider,
                search=search,
                page=1,
                page_size=10000,
            )
        except Exception:
            continue

        for s in part.sessions or []:
            exec_user_name = (getattr(s, "exec_user", "") or "").strip() or user_home.name
            s.exec_user = exec_user_name
            key = f"{exec_user_name}:{getattr(s, 'provider', '')}:{s.id}"
            prev = merged.get(key)
            if prev is None or int(getattr(s, "updated_at", 0) or 0) > int(getattr(prev, "updated_at", 0) or 0):
                merged[key] = s

    all_sessions = sorted(merged.values(), key=lambda s: int(getattr(s, "updated_at", 0) or 0), reverse=True)
    total = len(all_sessions)
    start = (page - 1) * page_size
    end = start + page_size
    result = SessionListResponse(
        total=total,
        page=page,
        page_size=page_size,
        sessions=all_sessions[start:end],
    )

    # Filter out hidden history sessions (deleted promoted sessions)
    try:
        storage = get_session_storage()
        hidden_ids = storage.get_hidden_history_sessions()
        if hidden_ids and result.sessions:
            before_count = len(result.sessions)
            result.sessions = [s for s in result.sessions if s.id not in hidden_ids]
            filtered_count = before_count - len(result.sessions)
            if filtered_count > 0:
                result.total = max(0, result.total - filtered_count)
    except Exception as e:
        logger.debug(f"Failed to filter hidden history sessions: {e}")

    return result


@router.get("/sessions/{provider}/{session_id}/messages", response_model=SessionMessagesResponse)
async def get_history_session_messages(
    provider: str,
    session_id: str,
    exec_user: str = Query(default="", description="Exec user for home directory resolution"),
    config_path: Optional[str] = Query(default=None, description="Custom config path for alias (e.g. ~/.claude-internal)"),
):
    """Get messages and tool calls for a specific history session.

    Path parameters:
    - provider: Provider or alias name (e.g. claude, codex, codebuddy, gemini, claude-internal)
    - session_id: Session ID
    """
    user_homes = _resolve_history_user_homes(exec_user)

    candidate_configs: List[Path] = []

    # Resolve config paths for explicit or inferred providers/aliases.
    if config_path:
        for user_home in user_homes:
            resolved = _resolve_tilde(config_path, user_home)
            if resolved.is_absolute():
                candidate_configs.append(resolved)
    else:
        if provider in _PROVIDER_CONFIG_DIRS:
            for user_home in user_homes:
                candidate_configs.append(user_home / _PROVIDER_CONFIG_DIRS[provider])
        else:
            is_alias = any(provider.startswith(pname) for pname in _PROVIDER_CONFIG_DIRS)
            if not is_alias:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown provider '{provider}'. Provide config_path for custom aliases.",
                )
            for user_home in user_homes:
                candidate_configs.append(user_home / f".{provider}")

    # De-duplicate while preserving order
    unique_candidates: List[Path] = []
    seen = set()
    for cp in candidate_configs:
        key = str(cp)
        if key in seen:
            continue
        seen.add(key)
        unique_candidates.append(cp)

    if not unique_candidates:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    service = _get_history_service()
    for resolved_config in unique_candidates:
        if not resolved_config.is_absolute():
            continue
        result = await service.get_session_detail(
            provider=provider,
            config_path=resolved_config,
            session_id=session_id,
        )
        if result is not None:
            return result

    raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")


class PromoteHistoryRequest(BaseModel):
    project_path: str = Field(..., description="History project path")
    exec_user: str = Field(default="", description="Exec user for runtime session")
    mode: str = Field(default="full", description="Import mode: full (default, all messages) | windowed (last 50, truncated)")


class PromoteHistoryResponse(BaseModel):
    runtime_session_id: str
    created: bool = True


class MemoryStateResponse(BaseModel):
    workspace: str
    has_long_term_memory: bool
    has_history: bool
    long_term_chars: int
    history_chars: int
    history_entries: int


class RestoreMemoryRequest(BaseModel):
    workspace: Optional[str] = Field(default=None, description="Nanobot workspace path")
    max_chars: int = Field(default=8000, ge=512, le=64000)
    max_entries: int = Field(default=8, ge=1, le=100)
    inject_message: bool = Field(default=True, description="Append restored context as a system message")
    set_bootstrap: bool = Field(default=True, description="Set restored context as one-shot bootstrap context")


class RestoreMemoryResponse(BaseModel):
    session_id: str
    workspace: str
    restored_chars: int
    restored_entries: int
    injected_message: bool = False
    bootstrap_updated: bool = False


def _resolve_base_provider(provider_or_alias: str) -> str:
    p = (provider_or_alias or "").strip().lower()
    if p in _PROVIDER_CONFIG_DIRS:
        return p
    for base in _PROVIDER_CONFIG_DIRS:
        if p.startswith(base):
            return base
    return p or "claude"


def _build_bootstrap_context(detail: SessionMessagesResponse, mode: str = "full") -> str:
    """Build bootstrap context text from history messages.

    Args:
        detail: Parsed history session messages.
        mode: ``"full"`` (all messages, no truncation) or ``"windowed"``
              (last 50 messages, each truncated to 800 chars).
    """
    msgs = detail.messages or []
    if not msgs:
        return "(历史会话没有可用消息)"

    effective_mode = (mode or "full").strip().lower()
    # Backward compat
    if effective_mode == "summary":
        effective_mode = "windowed"
    if effective_mode not in ("full", "windowed"):
        effective_mode = "full"

    if effective_mode == "windowed":
        msgs = msgs[-50:]

    lines = []
    for m in msgs:
        role = "用户" if m.role == "user" else "助手"
        content = (m.content or "").strip()
        if not content:
            continue
        if effective_mode == "windowed" and len(content) > 800:
            content = content[:800] + "…(截断)"
        lines.append(f"[{role}] {content}")

    return "\n\n".join(lines) if lines else "(历史会话没有可用消息)"


@router.get("/memory/state", response_model=MemoryStateResponse)
async def get_memory_state(
    workspace: Optional[str] = Query(default=None, description="Nanobot workspace path"),
):
    """Expose long-term vs consolidated history memory state."""
    resolved_workspace = _resolve_nanobot_workspace_path(workspace)
    store = MemoryStore(resolved_workspace)
    state = store.get_memory_state()
    return MemoryStateResponse(
        workspace=str(resolved_workspace),
        has_long_term_memory=bool(state.get("has_long_term_memory", False)),
        has_history=bool(state.get("has_history", False)),
        long_term_chars=int(state.get("long_term_chars", 0) or 0),
        history_chars=int(state.get("history_chars", 0) or 0),
        history_entries=int(state.get("history_entries", 0) or 0),
    )


@router.post("/sessions/{session_id}/restore-memory", response_model=RestoreMemoryResponse)
async def restore_memory_context(
    session_id: str,
    req: RestoreMemoryRequest,
):
    """Restore consolidated memory context into a runtime session."""
    storage = get_session_storage()
    meta = storage.get_session_meta(session_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Runtime session '{session_id}' not found")

    resolved_workspace = _resolve_nanobot_workspace_path(req.workspace)
    store = MemoryStore(resolved_workspace)
    memory_state = store.get_memory_state()
    restored_context = store.build_recovery_context(max_chars=req.max_chars, max_entries=req.max_entries)
    if not restored_context.strip():
        raise HTTPException(status_code=404, detail="No consolidated memory content available")

    injected = False
    if req.inject_message:
        restored_message = StoredMessage(
            id=f"memory-restore-{uuid.uuid4().hex[:12]}",
            role="system",
            content=f"[Recovered Memory Context]\n{restored_context}",
            status=MessageStatus.COMPLETE,
        )
        injected = storage.add_session_message(session_id, restored_message)
        if not injected:
            raise HTTPException(status_code=500, detail="Failed to inject restored context message")

    bootstrap_updated = False
    if req.set_bootstrap:
        bootstrap_updated = storage.set_history_bootstrap_context(session_id, restored_context)

    return RestoreMemoryResponse(
        session_id=session_id,
        workspace=str(resolved_workspace),
        restored_chars=len(restored_context),
        restored_entries=min(int(memory_state.get("history_entries", 0) or 0), req.max_entries),
        injected_message=injected,
        bootstrap_updated=bootstrap_updated,
    )


@router.post("/sessions/{provider}/{session_id}/promote", response_model=PromoteHistoryResponse)
async def promote_history_session(
    provider: str,
    session_id: str,
    req: PromoteHistoryRequest,
):
    """Promote a local history session into a runtime session for continued chat."""
    project_path = (req.project_path or "").strip()
    if not project_path:
        raise HTTPException(status_code=400, detail="project_path is required")

    user = req.exec_user or settings.exec_user or "ubuntu"
    home_base = settings.user_home_base or "/home"
    user_home = Path(home_base) / user

    if provider in _PROVIDER_CONFIG_DIRS:
        resolved_config = user_home / _PROVIDER_CONFIG_DIRS[provider]
    else:
        resolved_config = user_home / f".{provider}"

    service = _get_history_service()
    detail = await service.get_session_detail(
        provider=provider,
        config_path=resolved_config,
        session_id=session_id,
    )
    if detail is None:
        raise HTTPException(status_code=404, detail=f"History session '{session_id}' not found")

    storage = get_session_storage()
    mapped = storage.get_history_runtime_mapping(provider, session_id, project_path)
    if mapped and storage.get_session_meta(mapped):
        # Back-fill cli_session_id if missing (e.g. promoted by older server version)
        if not storage.get_cli_session_id(mapped):
            storage.set_cli_session_id(mapped, session_id)
            logger.info(f"Back-filled cli_session_id for existing mapping {mapped} -> {session_id}")
        return PromoteHistoryResponse(runtime_session_id=mapped, created=False)

    from ..utils.ids import gen_session_id
    runtime_session_id = gen_session_id()
    base_provider = _resolve_base_provider(provider)

    title = (detail.session.title if detail.session else None) or f"History: {session_id}"
    now_ms = int(time.time() * 1000)
    meta = SessionMeta(
        id=runtime_session_id,
        thread_id=runtime_session_id,
        run_id=None,
        title=title,
        username=user,
        exec_user=user,
        provider=base_provider,
        alias=provider,
        created_at=now_ms,
        updated_at=now_ms,
        message_count=0,
        status=SessionStatus.IDLE,
        exec_dir=project_path,
    )
    storage.save_session_meta(meta)

    mode = (req.mode or "full").strip().lower()
    if mode == "full":
        for msg in detail.messages or []:
            role = msg.role if msg.role in ("user", "assistant", "system") else "assistant"
            imported = StoredMessage(
                id=f"hist-{msg.id}",
                role=role,
                content=msg.content or "",
                status=MessageStatus.COMPLETE,
                tool_call_ids=msg.tool_call_ids,
                content_segments=msg.content_segments,
            )
            storage.add_session_message(runtime_session_id, imported)
        for tc in detail.tool_calls or []:
            tc_copy = tc.model_copy(deep=True)
            tc_copy.id = f"hist-{tc.id}"
            if tc_copy.parent_message_id:
                tc_copy.parent_message_id = f"hist-{tc_copy.parent_message_id}"
            storage.save_tool_call(runtime_session_id, tc_copy)

    bootstrap_context = _build_bootstrap_context(detail, mode=mode)
    storage.set_history_bootstrap_context(runtime_session_id, bootstrap_context)
    storage.set_exec_dir_override(runtime_session_id, project_path)
    storage.set_workspace_provider(runtime_session_id, base_provider)
    storage.set_workspace_alias(runtime_session_id, provider)
    storage.set_inherited_session(runtime_session_id, f"history:{provider}:{session_id}")
    storage.set_history_runtime_mapping(provider, session_id, project_path, runtime_session_id)

    # Store the original CLI session ID so that follow-up messages use
    # --resume <UUID> to precisely restore the CLI session instead of
    # starting a brand-new session or falling back to -c / --resume latest.
    storage.set_cli_session_id(runtime_session_id, session_id)

    return PromoteHistoryResponse(runtime_session_id=runtime_session_id, created=True)


class FetchFromCliRequest(BaseModel):
    exec_user: str = Field(default="", description="Exec user for home directory resolution")


class FetchFromCliResponse(BaseModel):
    session_id: str
    cli_session_id: str
    provider: str
    messages_imported: int = 0
    tool_calls_imported: int = 0


@router.post("/sessions/{session_id}/fetch-from-cli", response_model=FetchFromCliResponse)
async def fetch_from_cli(
    session_id: str,
    req: FetchFromCliRequest,
):
    """Fetch/refresh CLI file data into an existing Runtime session.

    Reads the CLI JSONL file associated with the Runtime session's cli_session_id
    and overwrites the Redis messages and tool calls.
    """
    storage = get_session_storage()
    meta = storage.get_session_meta(session_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Runtime session '{session_id}' not found")

    # Task sessions are created by the task executor, not from CLI.
    # Fetching from CLI would overwrite runtime messages with unrelated data.
    try:
        _task_id = storage._redis.hget(f"session:{session_id}:meta", "task_id")
    except Exception:
        _task_id = None
    if _task_id:
        raise HTTPException(
            status_code=400,
            detail="Task sessions cannot be refreshed from CLI — their data comes from the task executor, not CLI history files.",
        )

    cli_session_id = storage.get_cli_session_id(session_id)

    # Determine provider
    provider = meta.provider or "claude"

    user = req.exec_user or settings.exec_user or "ubuntu"
    home_base = settings.user_home_base or "/home"
    user_home = Path(home_base) / user

    if provider in _PROVIDER_CONFIG_DIRS:
        resolved_config = user_home / _PROVIDER_CONFIG_DIRS[provider]
    else:
        resolved_config = user_home / f".{provider}"

    service = _get_history_service()

    # Auto-discover cli_session_id if not set:
    # Use exec_dir (project_path) + provider to find the latest CLI session
    if not cli_session_id:
        # Resolve project_path: exec_dir_override > meta.exec_dir > session directory
        project_path = (
            storage.get_exec_dir_override(session_id)
            or (meta.exec_dir if meta.exec_dir else None)
        )
        if not project_path:
            # Fallback: use the session's default directory {user_home}/.nexus/sessions/{session_id}
            project_path = str(user_home / ".nexus" / "sessions" / session_id)
        if not project_path:
            raise HTTPException(
                status_code=400,
                detail="This session has no CLI session ID and no project path. Cannot auto-discover.",
            )
        parser = service._resolve_parser_for_alias(provider)
        if parser is None:
            raise HTTPException(
                status_code=400,
                detail=f"No history parser available for provider '{provider}'.",
            )
        sessions = parser.list_sessions(resolved_config, project_path)
        if not sessions:
            raise HTTPException(
                status_code=404,
                detail=f"No CLI sessions found for provider '{provider}' in project '{project_path}'.",
            )
        # Pick the most recent session
        sessions.sort(key=lambda s: s.updated_at or s.created_at or 0, reverse=True)
        cli_session_id = sessions[0].id
        # Persist for future use
        storage.set_cli_session_id(session_id, cli_session_id)
        logger.info(f"Auto-discovered cli_session_id={cli_session_id} for session {session_id}")

    detail = await service.get_session_detail(
        provider=provider,
        config_path=resolved_config,
        session_id=cli_session_id,
    )

    if detail is None:
        raise HTTPException(
            status_code=404,
            detail=f"CLI session '{cli_session_id}' not found in {provider} history files",
        )

    # Clear existing messages and tool calls
    storage.clear_session_messages(session_id)
    storage.clear_session_tool_calls(session_id)

    # Re-import
    msg_count = 0
    for msg in detail.messages or []:
        role = msg.role if msg.role in ("user", "assistant", "system") else "assistant"
        imported = StoredMessage(
            id=f"hist-{msg.id}",
            role=role,
            content=msg.content or "",
            status=MessageStatus.COMPLETE,
            tool_call_ids=msg.tool_call_ids,
            content_segments=msg.content_segments,
        )
        storage.add_session_message(session_id, imported)
        msg_count += 1

    tc_count = 0
    for tc in detail.tool_calls or []:
        tc_copy = tc.model_copy(deep=True)
        tc_copy.id = f"hist-{tc.id}"
        if tc_copy.parent_message_id:
            tc_copy.parent_message_id = f"hist-{tc_copy.parent_message_id}"
        storage.save_tool_call(session_id, tc_copy)
        tc_count += 1

    logger.info(
        "Fetched CLI data for session %s: %d messages, %d tool calls from %s:%s",
        session_id, msg_count, tc_count, provider, cli_session_id,
    )

    return FetchFromCliResponse(
        session_id=session_id,
        cli_session_id=cli_session_id,
        provider=provider,
        messages_imported=msg_count,
        tool_calls_imported=tc_count,
    )
