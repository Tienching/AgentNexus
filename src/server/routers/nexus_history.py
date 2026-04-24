# -*- coding: utf-8 -*-
"""History API Router for NexusHub.

Provides REST API endpoints for reading native CLI session history files
from Claude Code, Codex, CodeBuddy, and Gemini providers.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from ..config import settings
from ..logger import get_logger
from ..models import (
    SessionMessagesResponse,
    SessionMeta,
    SessionStatus,
    StoredMessage,
    MessageStatus,
)
from ..services.session_storage import get_session_storage
from .nexus_auth import verify_nexus_auth
from .nexus_history_helpers import (
    PROVIDER_CONFIG_DIRS as _PROVIDER_CONFIG_DIRS,
    build_alias_config_map as _build_alias_config_map,
    build_bootstrap_context as _build_bootstrap_context,
    build_runtime_session_meta,
    get_history_observability_snapshot,
    get_history_service as _get_history_service,
    import_history_detail,
    infer_history_project_path,
    record_history_compat_hit as _record_history_compat_hit,
    record_history_read_failure as _record_history_read_failure,
    resolve_base_provider as _resolve_base_provider,
    resolve_exec_user_home,
    resolve_history_candidate_configs as _resolve_history_candidate_configs,
    resolve_history_user_homes as _resolve_history_user_homes,
    resolve_nexus_workspace_path as _resolve_nexus_workspace_path,
    resolve_provider_config_path,
)
from .nexus_history_queries import (
    collect_history_projects,
    collect_history_sessions,
)
from .nexus_models import (
    HistoryProjectProviderSummary,
    HistoryProjectSummary,
    HistorySessionListResponse,
    HistorySessionSummary,
    build_history_session_summary,
)

from src.nanobot.agent.memory import MemoryStore

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/nexus/history",
    tags=["nexus-history"],
    dependencies=[Depends(verify_nexus_auth)],
)


@router.get("/projects", response_model=List[HistoryProjectSummary])
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
    return await collect_history_projects(
        service=_get_history_service(),
        user_homes=_resolve_history_user_homes(exec_user),
        custom_paths=custom_paths,
        provider=provider,
        build_alias_config_map=_build_alias_config_map,
    )


@router.get("/sessions", response_model=HistorySessionListResponse)
async def list_history_sessions(
    project_path: str = Query(default="", description="Optional project workspace path (e.g. /home/bob/myproject). Leave empty to search all projects."),
    exec_user: str = Query(default="", description="Exec user for home directory resolution"),
    custom_paths: str = Query(default="", description="JSON-encoded dict of alias->configPath"),
    provider: Optional[str] = Query(default=None, description="Filter by provider (claude/codex/codebuddy/gemini)"),
    search: Optional[str] = Query(default=None, description="Search text for session title"),
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=2000, description="Page size"),
    per_alias_limit: int = Query(
        default=0,
        ge=0,
        le=500,
        description="When > 0, return at most N sessions per (provider, alias) group. "
                    "Overrides page/page_size and guarantees every provider+alias is represented in the first response.",
    ),
):
    """List local history sessions.

    This endpoint reads native CLI session files from the local filesystem.
    It does NOT access Redis — runtime sessions use a separate endpoint.

    Optional parameter:
    - project_path: When provided, filter history to that workspace path.
      When empty, aggregate history across all projects.

    Optional parameters:
    - custom_paths: JSON dict mapping alias names to their config directories
      e.g. {"claude-internal":"~/.claude-internal","codex-internal":"~/.codex-internal"}
    - per_alias_limit: Take top N per (provider, alias). Useful for UI that groups by provider.
    """
    return await collect_history_sessions(
        service=_get_history_service(),
        user_homes=_resolve_history_user_homes(exec_user),
        project_path=project_path,
        custom_paths=custom_paths,
        provider=provider,
        search=search,
        page=page,
        page_size=page_size,
        per_alias_limit=per_alias_limit,
        build_alias_config_map=_build_alias_config_map,
        get_session_storage=get_session_storage,
        record_history_read_failure=_record_history_read_failure,
    )


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
    unique_candidates = _resolve_history_candidate_configs(
        provider,
        exec_user=exec_user,
        config_path=config_path,
    )

    if not unique_candidates:
        _record_history_read_failure(
            "get_history_session_messages",
            provider=provider,
            session_id=session_id,
            detail={"exec_user": exec_user, "config_path": config_path, "reason": "no_candidates"},
        )
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

    _record_history_read_failure(
        "get_history_session_messages",
        provider=provider,
        session_id=session_id,
        detail={
            "exec_user": exec_user,
            "config_path": config_path,
            "candidate_count": len(unique_candidates),
            "reason": "detail_not_found",
        },
    )

    raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")


@router.get("/sessions/{provider}/{session_id}/summary", response_model=HistorySessionSummary)
async def get_history_session_summary(
    provider: str,
    session_id: str,
    exec_user: str = Query(default="", description="Exec user for home directory resolution"),
    config_path: Optional[str] = Query(default=None, description="Custom config path for alias (e.g. ~/.claude-internal)"),
):
    """Get a stable read-only summary for a specific history session."""
    unique_candidates = _resolve_history_candidate_configs(
        provider,
        exec_user=exec_user,
        config_path=config_path,
    )
    service = _get_history_service()
    for resolved_config in unique_candidates:
        if not resolved_config.is_absolute():
            continue
        result = await service.get_session_detail(
            provider=provider,
            config_path=resolved_config,
            session_id=session_id,
        )
        if result is None:
            continue

        summary_source = result.session or SessionMeta(
            id=session_id,
            thread_id=session_id,
            title=f"History: {session_id}",
            username=settings.exec_user or "ubuntu",
            provider=_resolve_base_provider(provider),
            alias=provider,
        )
        summary = build_history_session_summary(
            summary_source,
            resumable=True,
            group_key=f"{_resolve_base_provider(provider)}:{provider}",
        )
        return summary

    _record_history_read_failure(
        "get_history_session_summary",
        provider=provider,
        session_id=session_id,
        detail={
            "exec_user": exec_user,
            "config_path": config_path,
            "candidate_count": len(unique_candidates),
            "reason": "detail_not_found",
        },
    )
    raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")


class PromoteHistoryRequest(BaseModel):
    project_path: str = Field(default="", description="Optional history project path; when omitted we use the session's own recorded exec_dir/workspace")
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
    workspace: Optional[str] = Field(default=None, description="Nexus workspace path")
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

@router.get("/memory/state", response_model=MemoryStateResponse)
async def get_memory_state(
    workspace: Optional[str] = Query(default=None, description="Nexus workspace path"),
):
    """Expose long-term vs consolidated history memory state."""
    resolved_workspace = _resolve_nexus_workspace_path(workspace)
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

    resolved_workspace = _resolve_nexus_workspace_path(req.workspace)
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


async def _resume_history_session(
    provider: str,
    session_id: str,
    req: PromoteHistoryRequest,
    *,
    compat_route: bool = False,
    response: Optional[Response] = None,
):
    """Bind or resume a history session into a runtime session for continued chat."""
    user, user_home = resolve_exec_user_home(req.exec_user)
    resolved_config = resolve_provider_config_path(provider, user_home=user_home)

    service = _get_history_service()
    project_path = (req.project_path or "").strip()
    detail = await service.get_session_detail(
        provider=provider,
        config_path=resolved_config,
        session_id=session_id,
    )
    if detail is None:
        _record_history_read_failure(
            "resume_history_session",
            provider=provider,
            session_id=session_id,
            detail={
                "project_path": project_path or None,
                "resolved_config": str(resolved_config),
                "compat_route": compat_route,
            },
        )
        raise HTTPException(status_code=404, detail=f"History session '{session_id}' not found")

    if not project_path:
        project_path = infer_history_project_path(detail)
    if not project_path:
        raise HTTPException(
            status_code=400,
            detail="project_path is missing and could not be inferred from history session metadata",
        )

    storage = get_session_storage()
    base_provider = _resolve_base_provider(provider)
    mapped = storage.get_history_runtime_mapping(provider, session_id, project_path)
    if mapped and storage.get_session_meta(mapped):
        # Back-fill cli_session_id if missing (e.g. promoted by older server version)
        if not storage.get_cli_session_id(mapped):
            storage.set_cli_session_id(mapped, session_id)
            logger.info(f"Back-filled cli_session_id for existing mapping {mapped} -> {session_id}")
        if hasattr(storage, "upsert_execution_binding"):
            storage.upsert_execution_binding(
                mapped,
                cli_session_id=session_id,
                provider=base_provider,
                alias=provider,
                exec_user=user,
                work_dir=project_path,
                source_type="history",
                source_session_id=session_id,
                session_kind="chat",
            )
        if compat_route:
            _record_history_compat_hit(
                "legacy_promote_route",
                provider=provider,
                session_id=session_id,
                detail={"project_path": project_path, "runtime_session_id": mapped},
            )
            if response is not None:
                response.headers["X-Nexus-History-Compat"] = "promote"
        return PromoteHistoryResponse(runtime_session_id=mapped, created=False)

    from ..utils.ids import gen_session_id

    runtime_session_id = gen_session_id()
    storage.save_session_meta(
        build_runtime_session_meta(
            runtime_session_id,
            detail,
            user=user,
            base_provider=base_provider,
            provider_alias=provider,
            source_session_id=session_id,
            project_path=project_path,
            now_ms=int(time.time() * 1000),
        )
    )

    mode = (req.mode or "full").strip().lower()
    if mode == "full":
        import_history_detail(storage, runtime_session_id, detail)

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

    if compat_route:
        _record_history_compat_hit(
            "legacy_promote_route",
            provider=provider,
            session_id=session_id,
            detail={"project_path": project_path, "runtime_session_id": runtime_session_id},
        )
        if response is not None:
            response.headers["X-Nexus-History-Compat"] = "promote"

    return PromoteHistoryResponse(runtime_session_id=runtime_session_id, created=True)


@router.post("/sessions/{provider}/{session_id}/resume", response_model=PromoteHistoryResponse)
async def resume_history_session(
    provider: str,
    session_id: str,
    req: PromoteHistoryRequest,
    response: Response,
):
    """Canonical History resume endpoint (read-only source → runtime binding)."""
    return await _resume_history_session(provider, session_id, req, compat_route=False, response=response)


@router.post("/sessions/{provider}/{session_id}/bind", response_model=PromoteHistoryResponse)
async def bind_history_session(
    provider: str,
    session_id: str,
    req: PromoteHistoryRequest,
    response: Response,
):
    """Alias for the canonical History resume endpoint."""
    return await _resume_history_session(provider, session_id, req, compat_route=False, response=response)


@router.post("/sessions/{provider}/{session_id}/promote", response_model=PromoteHistoryResponse)
async def promote_history_session(
    provider: str,
    session_id: str,
    req: PromoteHistoryRequest,
    response: Response,
):
    """Legacy compatibility alias for the old promote-to-runtime path."""
    return await _resume_history_session(provider, session_id, req, compat_route=True, response=response)


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
    response: Response,
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
    binding = storage.get_execution_binding(session_id)
    if (binding and binding.task_id) or getattr(meta, "task_id", None):
        raise HTTPException(
            status_code=400,
            detail="Task sessions cannot be refreshed from CLI — their data comes from the task executor, not CLI history files.",
        )

    cli_session_id = storage.get_cli_session_id(session_id)

    # Determine provider
    provider = meta.provider or "claude"

    user, user_home = resolve_exec_user_home(req.exec_user)
    resolved_config = resolve_provider_config_path(provider, user_home=user_home)

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
            _record_history_read_failure(
                "fetch_from_cli_missing_parser",
                provider=provider,
                session_id=session_id,
                detail={"project_path": project_path, "exec_user": user},
            )
            raise HTTPException(
                status_code=400,
                detail=f"No history parser available for provider '{provider}'.",
            )
        sessions = parser.list_sessions(resolved_config, project_path)
        if not sessions:
            _record_history_read_failure(
                "fetch_from_cli_no_sessions",
                provider=provider,
                session_id=session_id,
                detail={"project_path": project_path, "exec_user": user, "resolved_config": str(resolved_config)},
            )
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
        _record_history_compat_hit(
            "fetch_from_cli_autodiscover",
            provider=provider,
            session_id=session_id,
            detail={"project_path": project_path, "resolved_config": str(resolved_config)},
        )
        response.headers["X-Nexus-History-Compat"] = "fetch-from-cli-autodiscover"

    detail = await service.get_session_detail(
        provider=provider,
        config_path=resolved_config,
        session_id=cli_session_id,
    )

    if detail is None:
        _record_history_read_failure(
            "fetch_from_cli_detail",
            provider=provider,
            session_id=session_id,
            detail={
                "cli_session_id": cli_session_id,
                "resolved_config": str(resolved_config),
                "exec_user": user,
            },
        )
        raise HTTPException(
            status_code=404,
            detail=f"CLI session '{cli_session_id}' not found in {provider} history files",
        )

    # Clear existing messages and tool calls
    storage.clear_session_messages(session_id)
    storage.clear_session_tool_calls(session_id)

    # Re-import
    msg_count, tc_count = import_history_detail(storage, session_id, detail)

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
