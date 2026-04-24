# -*- coding: utf-8 -*-
"""Query helpers for the Nexus history router."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..models import SessionMeta
from .nexus_models import (
    HistoryProjectProviderSummary,
    HistoryProjectSummary,
    HistorySessionListResponse,
    build_history_session_summary,
    group_history_session_summaries,
)


AliasConfigBuilder = Callable[[Path, str, Optional[str]], Dict[str, Path]]
HistoryFailureRecorder = Callable[..., None]
SessionStorageFactory = Callable[[], Any]


async def collect_history_projects(
    *,
    service: Any,
    user_homes: List[Path],
    custom_paths: str,
    provider: Optional[str],
    build_alias_config_map: AliasConfigBuilder,
) -> List[HistoryProjectSummary]:
    """Collect project summaries across one or more user homes."""
    merged_by_path: Dict[str, Dict[str, Any]] = {}
    for user_home in user_homes:
        alias_map = build_alias_config_map(user_home, custom_paths, provider)
        if not alias_map:
            continue

        entries = await service.list_projects(
            alias_config_map=alias_map,
            provider_filter=provider,
        )
        for entry in entries or []:
            _merge_project_entry(merged_by_path, entry)

    return _build_project_summaries(merged_by_path)


async def collect_history_sessions(
    *,
    service: Any,
    user_homes: List[Path],
    project_path: str,
    custom_paths: str,
    provider: Optional[str],
    search: Optional[str],
    page: int,
    page_size: int,
    build_alias_config_map: AliasConfigBuilder,
    get_session_storage: SessionStorageFactory,
    record_history_read_failure: HistoryFailureRecorder,
    per_alias_limit: int = 0,
) -> HistorySessionListResponse:
    """Collect and paginate session summaries across one or more user homes.

    When ``per_alias_limit`` > 0, the response is not globally paginated; instead
    every (provider, alias) bucket contributes at most ``per_alias_limit`` sessions
    (most recent first). This guarantees each configured provider/alias is visible
    in a single request and matches how the UI groups the list.
    """
    project_path = project_path.strip()
    ordered_user_homes = _prioritize_user_homes_for_project(user_homes, project_path)

    merged: Dict[str, SessionMeta] = {}
    for user_home in ordered_user_homes:
        alias_map = build_alias_config_map(user_home, custom_paths, provider)
        if not alias_map:
            continue

        try:
            if project_path:
                part = await service.list_all_sessions(
                    user_home=user_home,
                    project_path=project_path,
                    alias_config_map=alias_map,
                    provider_filter=provider,
                    search=search,
                    page=1,
                    page_size=10000,
                )
            else:
                part = await service.list_global_sessions(
                    alias_config_map=alias_map,
                    provider_filter=provider,
                    search=search,
                    page=1,
                    page_size=10000,
                    linux_user=user_home.name,
                )
        except Exception as exc:
            record_history_read_failure(
                "list_history_sessions",
                provider=provider,
                session_id=None,
                detail={
                    "project_path": project_path or None,
                    "user_home": str(user_home),
                    "error": str(exc),
                    "exception_type": type(exc).__name__,
                },
            )
            continue

        for session in part.sessions or []:
            _merge_session_record(merged, session, user_home)

    sessions = service.sort_history_sessions(list(merged.values()))
    sessions = _filter_hidden_history_sessions(
        sessions,
        get_session_storage=get_session_storage,
        provider=provider,
        project_path=project_path,
        record_history_read_failure=record_history_read_failure,
    )

    summaries = [build_history_session_summary(session) for session in sessions]
    total = len(summaries)

    if per_alias_limit and per_alias_limit > 0:
        # Bucket by (provider, alias) and take top N per bucket.
        # `summaries` is already time-sorted (newest first) by `sort_history_sessions`,
        # so per-bucket truncation preserves recency ordering.
        buckets: Dict[str, List] = {}
        for summary in summaries:
            prov = (summary.provider or "unknown").strip().lower() or "unknown"
            alias = (summary.alias or summary.provider or "unknown").strip().lower() or "unknown"
            key = f"{prov}::{alias}"
            buckets.setdefault(key, []).append(summary)

        page_sessions = []
        for bucket in buckets.values():
            page_sessions.extend(bucket[:per_alias_limit])

        # Re-sort the combined slice so the flat `sessions` list stays time-ordered.
        page_sessions.sort(
            key=lambda s: int(getattr(s, "updated_at", 0) or getattr(s, "created_at", 0) or 0),
            reverse=True,
        )
        groups = group_history_session_summaries(page_sessions)
        return HistorySessionListResponse(
            total=total,
            page=1,
            page_size=len(page_sessions),
            sessions=page_sessions,
            groups=groups,
        )

    start = (page - 1) * page_size
    end = start + page_size
    page_sessions = summaries[start:end]
    groups = group_history_session_summaries(page_sessions)

    return HistorySessionListResponse(
        total=total,
        page=page,
        page_size=page_size,
        sessions=page_sessions,
        groups=groups,
    )



def _merge_project_entry(merged_by_path: Dict[str, Dict[str, Any]], entry: Dict[str, Any]) -> None:
    path = entry.get("path")
    if not path:
        return

    bucket = merged_by_path.setdefault(
        path,
        {
            "path": path,
            "providers": [],
            "total_sessions": 0,
            "last_active": 0,
        },
    )

    provider_counter = {
        (provider.get("provider"), provider.get("alias")): int(provider.get("session_count", 0) or 0)
        for provider in bucket.get("providers", [])
    }
    for provider in entry.get("providers", []) or []:
        key = (provider.get("provider"), provider.get("alias"))
        provider_counter[key] = provider_counter.get(key, 0) + int(provider.get("session_count", 0) or 0)

    bucket["providers"] = [
        {"provider": key[0], "alias": key[1], "session_count": count}
        for key, count in provider_counter.items()
    ]
    bucket["total_sessions"] = sum(provider["session_count"] for provider in bucket["providers"])
    bucket["last_active"] = max(
        int(bucket.get("last_active", 0) or 0),
        int(entry.get("last_active", 0) or 0),
    )
    if entry.get("gemini_hash"):
        bucket["gemini_hash"] = entry.get("gemini_hash")



def _build_project_summaries(merged_by_path: Dict[str, Dict[str, Any]]) -> List[HistoryProjectSummary]:
    result: List[HistoryProjectSummary] = []
    for bucket in sorted(
        merged_by_path.values(),
        key=lambda item: int(item.get("last_active", 0) or 0),
        reverse=True,
    ):
        providers = sorted(
            bucket.get("providers", []) or [],
            key=lambda item: (
                str(item.get("provider") or "").lower(),
                str(item.get("alias") or "").lower(),
            ),
        )
        result.append(
            HistoryProjectSummary(
                path=bucket["path"],
                providers=[
                    HistoryProjectProviderSummary(
                        provider=str(provider.get("provider") or ""),
                        alias=str(provider.get("alias") or ""),
                        session_count=int(provider.get("session_count", 0) or 0),
                    )
                    for provider in providers
                ],
                total_sessions=int(bucket.get("total_sessions", 0) or 0),
                last_active=int(bucket.get("last_active", 0) or 0),
                gemini_hash=bucket.get("gemini_hash"),
            )
        )
    return result



def _prioritize_user_homes_for_project(user_homes: List[Path], project_path: str) -> List[Path]:
    """Prefer the project owner home when aggregating across all users."""
    if not project_path:
        return list(user_homes)

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
        return [project_owner_home] + [home for home in user_homes if home != project_owner_home]
    return list(user_homes)



def _merge_session_record(merged: Dict[str, SessionMeta], session: SessionMeta, user_home: Path) -> None:
    exec_user_name = (getattr(session, "exec_user", "") or "").strip() or user_home.name
    session.exec_user = exec_user_name
    alias_name = (getattr(session, "alias", None) or getattr(session, "provider", None) or "").strip().lower()
    provider_name = (getattr(session, "provider", None) or "").strip().lower()
    key = f"{exec_user_name}:{provider_name}:{alias_name}:{session.id}"
    previous = merged.get(key)
    if previous is None or int(getattr(session, "updated_at", 0) or 0) > int(getattr(previous, "updated_at", 0) or 0):
        merged[key] = session



def _filter_hidden_history_sessions(
    sessions: List[SessionMeta],
    *,
    get_session_storage: SessionStorageFactory,
    provider: Optional[str],
    project_path: str,
    record_history_read_failure: HistoryFailureRecorder,
) -> List[SessionMeta]:
    try:
        storage = get_session_storage()
        hidden_ids = set(storage.get_hidden_history_sessions() or [])
        if hidden_ids:
            return [session for session in sessions if getattr(session, "id", None) not in hidden_ids]
    except Exception as exc:
        record_history_read_failure(
            "hidden_history_sessions",
            provider=provider,
            session_id=None,
            detail={
                "project_path": project_path or None,
                "error": str(exc),
                "exception_type": type(exc).__name__,
            },
        )
    return sessions
