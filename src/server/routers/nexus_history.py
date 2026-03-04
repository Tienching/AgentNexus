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
from typing import Dict, Optional
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


def _build_alias_config_map(
    user_home: Path,
    custom_paths_str: str,
    provider_filter: Optional[str] = None,
) -> Dict[str, Path]:
    """Build alias -> config_path mapping from defaults + custom_paths.

    Returns a dict mapping alias/provider names to their resolved config directory paths.
    """
    alias_map: Dict[str, Path] = {}

    # Add default providers
    for provider, config_dir in _PROVIDER_CONFIG_DIRS.items():
        if provider_filter and provider != provider_filter:
            continue
        alias_map[provider] = user_home / config_dir

    # Parse and add custom alias paths
    if custom_paths_str:
        try:
            custom_paths: Dict[str, str] = json.loads(custom_paths_str)
        except (json.JSONDecodeError, TypeError):
            custom_paths = {}

        for alias_name, path_str in custom_paths.items():
            if provider_filter and alias_name != provider_filter:
                # Check if this alias maps to the filtered provider
                base_provider = None
                for pname in _PROVIDER_PARSER_MAP:
                    if alias_name.startswith(pname):
                        base_provider = pname
                        break
                if base_provider != provider_filter:
                    continue

            resolved = _resolve_tilde(path_str, user_home)
            if resolved.is_absolute():
                alias_map[alias_name] = resolved
            else:
                logger.warning("Skipping non-absolute path for alias '%s': %s", alias_name, path_str)

    return alias_map


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
    user = exec_user or settings.exec_user or "ubuntu"
    home_base = settings.user_home_base or "/home"
    user_home = Path(home_base) / user

    alias_map = _build_alias_config_map(user_home, custom_paths, provider)

    service = _get_history_service()
    result = await service.list_projects(
        alias_config_map=alias_map,
        provider_filter=provider,
    )
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
    user = exec_user or settings.exec_user or "ubuntu"
    home_base = settings.user_home_base or "/home"
    user_home = Path(home_base) / user

    # Security: verify project_path is under user_home
    try:
        resolved_project = Path(project_path).resolve()
        if not str(resolved_project).startswith(str(user_home.resolve())):
            # Allow project paths outside user_home for flexibility
            # but log a warning
            logger.debug(
                "project_path %s is outside user_home %s",
                project_path, user_home,
            )
    except (ValueError, OSError):
        pass

    alias_map = _build_alias_config_map(user_home, custom_paths, provider)

    service = _get_history_service()
    result = await service.list_all_sessions(
        user_home=user_home,
        project_path=project_path,
        alias_config_map=alias_map,
        provider_filter=provider,
        search=search,
        page=page,
        page_size=page_size,
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
    user = exec_user or settings.exec_user or "ubuntu"
    home_base = settings.user_home_base or "/home"
    user_home = Path(home_base) / user

    # Resolve config path
    if config_path:
        resolved_config = _resolve_tilde(config_path, user_home)
    else:
        # Try to determine config path from provider name
        if provider in _PROVIDER_CONFIG_DIRS:
            resolved_config = user_home / _PROVIDER_CONFIG_DIRS[provider]
        else:
            # Try as alias prefix (e.g. claude-internal -> check if starts with known provider)
            resolved_config = None
            for pname, config_dir in _PROVIDER_CONFIG_DIRS.items():
                if provider.startswith(pname):
                    # Alias — use provider name as config dir (e.g. .claude-internal)
                    resolved_config = user_home / f".{provider}"
                    break
            if resolved_config is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown provider '{provider}'. Provide config_path for custom aliases.",
                )

    if not resolved_config.is_absolute():
        raise HTTPException(status_code=400, detail="config_path must resolve to an absolute path")

    service = _get_history_service()
    result = await service.get_session_detail(
        provider=provider,
        config_path=resolved_config,
        session_id=session_id,
    )

    if result is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    return result


class PromoteHistoryRequest(BaseModel):
    project_path: str = Field(..., description="History project path")
    exec_user: str = Field(default="", description="Exec user for runtime session")
    mode: str = Field(default="full", description="Import mode: full (default, all messages) | windowed (last 50, truncated)")


class PromoteHistoryResponse(BaseModel):
    runtime_session_id: str
    created: bool = True


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
