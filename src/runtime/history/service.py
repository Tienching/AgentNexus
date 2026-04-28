# -*- coding: utf-8 -*-
"""History service — aggregates parsers and provides unified query interface."""

import asyncio
import hashlib
import logging
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional
from weakref import WeakSet

from ..models.session import SessionListResponse, SessionMeta, SessionMessagesResponse
from .base_parser import BaseHistoryParser, HistorySessionDetail

logger = logging.getLogger(__name__)

# In-memory TTL caches
_CACHE_TTL_SECONDS = 300          # sessions / detail: 5 minutes
_PROJECTS_CACHE_TTL_SECONDS = 30  # project list: 30 seconds (frequent refreshes during active chats)


class _CacheEntry:
    __slots__ = ("value", "expires_at")

    def __init__(self, value: Any, ttl: float = _CACHE_TTL_SECONDS):
        self.value = value
        self.expires_at = time.monotonic() + ttl

    @property
    def expired(self) -> bool:
        return time.monotonic() > self.expires_at


class HistoryService:
    """Aggregates history parsers and provides cross-provider session queries.

    All file I/O is wrapped in asyncio.to_thread to avoid blocking the event loop.
    """

    _instances = WeakSet()

    def __init__(self):
        self._parsers: Dict[str, BaseHistoryParser] = {}
        self._cache: Dict[str, _CacheEntry] = {}
        self.__class__._instances.add(self)

    def register_parser(self, parser: BaseHistoryParser) -> None:
        """Register a history parser by its provider name."""
        self._parsers[parser.provider_name] = parser

    def register_parsers(self, parsers: List[BaseHistoryParser]) -> None:
        """Register multiple parsers in order."""
        for parser in parsers:
            self.register_parser(parser)

    @classmethod
    def default_parsers(cls) -> List[BaseHistoryParser]:
        """Build the standard parser set for all supported providers."""
        from .claude_parser import ClaudeHistoryParser
        from .codex_parser import CodexHistoryParser
        from .codebuddy_parser import CodeBuddyHistoryParser
        from .gemini_parser import GeminiHistoryParser

        return [
            ClaudeHistoryParser(),
            CodexHistoryParser(),
            CodeBuddyHistoryParser(),
            GeminiHistoryParser(),
        ]

    @classmethod
    def create_default(cls) -> "HistoryService":
        """Construct a HistoryService with the standard parser registry."""
        service = cls()
        service.register_parsers(cls.default_parsers())
        return service

    def registered_providers(self) -> List[str]:
        """Return provider keys currently registered on this service."""
        return sorted(self._parsers.keys())

    def get_parser(self, provider: str) -> Optional[BaseHistoryParser]:
        """Get a parser by provider name."""
        return self._parsers.get(provider)

    @staticmethod
    def _normalize_history_name(value: Optional[str], fallback: str = "unknown") -> str:
        normalized = (value or "").strip().lower()
        return normalized or fallback

    def history_session_sort_key(self, session: SessionMeta) -> tuple:
        """Sort by provider → alias → recency, with title/id tiebreakers."""
        provider = self._normalize_history_name(getattr(session, "provider", None))
        alias = self._normalize_history_name(getattr(session, "alias", None), provider)
        updated_at = int(getattr(session, "updated_at", None) or getattr(session, "created_at", None) or 0)
        title = (getattr(session, "title", "") or "").strip().lower()
        return (
            provider,
            alias,
            -updated_at,
            title,
            str(getattr(session, "id", "")),
        )

    def sort_history_sessions(self, sessions: List[SessionMeta]) -> List[SessionMeta]:
        """Return sessions ordered for History UI display."""
        return sorted(list(sessions or []), key=self.history_session_sort_key)

    def summarize_history_session(
        self,
        session: SessionMeta,
        *,
        resumable: bool = True,
    ) -> Dict[str, Any]:
        """Convert a SessionMeta into a stable History summary dictionary."""
        provider = self._normalize_history_name(getattr(session, "provider", None))
        alias = self._normalize_history_name(getattr(session, "alias", None), provider)
        exec_dir = getattr(session, "exec_dir", None) or None
        updated_at = int(getattr(session, "updated_at", None) or getattr(session, "created_at", None) or 0)
        return {
            "id": str(getattr(session, "id", "")),
            "thread_id": getattr(session, "thread_id", None) or str(getattr(session, "id", "")),
            "run_id": getattr(session, "run_id", None),
            "title": getattr(session, "title", None) or "New Session",
            "username": getattr(session, "username", None) or "",
            "exec_user": getattr(session, "exec_user", None) or None,
            "provider": provider,
            "alias": alias,
            "created_at": int(getattr(session, "created_at", None) or updated_at or 0),
            "updated_at": updated_at,
            "message_count": int(getattr(session, "message_count", 0) or 0),
            "status": getattr(session, "status", None) or "idle",
            "source": getattr(session, "source", None) or None,
            "exec_dir": exec_dir,
            "work_dir": exec_dir,
            "task_id": getattr(session, "task_id", None) or None,
            "source_session_id": getattr(session, "source_session_id", None) or None,
            "session_kind": getattr(session, "session_kind", None) or None,
            "resumable": bool(resumable),
            "group_key": f"{provider}:{alias}",
        }

    def group_history_session_summaries(
        self,
        sessions: List[SessionMeta],
        *,
        resumable: bool = True,
    ) -> List[Dict[str, Any]]:
        """Group history sessions by provider → alias for API consumers."""
        summaries = [
            self.summarize_history_session(session, resumable=resumable)
            for session in self.sort_history_sessions(sessions)
        ]

        provider_map: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        for summary in summaries:
            provider = self._normalize_history_name(summary.get("provider"))
            alias = self._normalize_history_name(summary.get("alias"), provider)
            provider_entry = provider_map.setdefault(
                provider,
                {
                    "provider": provider,
                    "total_sessions": 0,
                    "latest_updated_at": 0,
                    "aliases": OrderedDict(),
                },
            )
            provider_entry["total_sessions"] += 1
            provider_entry["latest_updated_at"] = max(
                int(provider_entry["latest_updated_at"]),
                int(summary.get("updated_at") or 0),
            )

            alias_entry = provider_entry["aliases"].setdefault(
                alias,
                {
                    "provider": provider,
                    "alias": alias,
                    "total_sessions": 0,
                    "latest_updated_at": 0,
                    "sessions": [],
                },
            )
            alias_entry["total_sessions"] += 1
            alias_entry["latest_updated_at"] = max(
                int(alias_entry["latest_updated_at"]),
                int(summary.get("updated_at") or 0),
            )
            alias_entry["sessions"].append(summary)

        groups: List[Dict[str, Any]] = []
        provider_rank = 0
        for provider_entry in sorted(
            provider_map.values(),
            key=lambda item: (
                -int(item["latest_updated_at"] or 0),
                str(item["provider"]),
            ),
        ):
            alias_groups: List[Dict[str, Any]] = []
            alias_rank = 0
            for alias_entry in sorted(
                provider_entry["aliases"].values(),
                key=lambda item: (
                    -int(item["latest_updated_at"] or 0),
                    str(item["alias"]),
                ),
            ):
                alias_sessions = sorted(
                    alias_entry["sessions"],
                    key=lambda item: (
                        -(int(item.get("updated_at") or 0)),
                        str(item.get("title") or "").lower(),
                        str(item.get("id") or ""),
                    ),
                )
                for session_summary in alias_sessions:
                    session_summary["provider_rank"] = provider_rank
                    session_summary["alias_rank"] = alias_rank
                alias_groups.append(
                    {
                        "provider": alias_entry["provider"],
                        "alias": alias_entry["alias"],
                        "total_sessions": int(alias_entry["total_sessions"]),
                        "latest_updated_at": int(alias_entry["latest_updated_at"]),
                        "sessions": alias_sessions,
                    }
                )
                alias_rank += 1
            groups.append(
                {
                    "provider": provider_entry["provider"],
                    "total_sessions": int(provider_entry["total_sessions"]),
                    "latest_updated_at": int(provider_entry["latest_updated_at"]),
                    "aliases": alias_groups,
                }
            )
            provider_rank += 1

        return groups

    def _get_cached(self, key: str) -> Optional[Any]:
        entry = self._cache.get(key)
        if entry is None or entry.expired:
            self._cache.pop(key, None)
            return None
        return entry.value

    def _set_cached(self, key: str, value: Any, ttl: float = _CACHE_TTL_SECONDS) -> None:
        self._cache[key] = _CacheEntry(value, ttl=ttl)

    def invalidate_project_caches(self) -> int:
        """Invalidate all project-list, session-list, global session, and
        session-detail caches.

        Called after a CLI execution completes so that the History UI
        immediately reflects updated file timestamps. The ``detail:`` prefix
        is included because detail snapshots otherwise live for 5 minutes and
        can serve stale messages when the underlying JSONL has changed (e.g.
        a ``/resume`` run appended new turns).

        Returns:
            Number of cache entries removed.
        """
        keys_to_remove = [
            k for k in self._cache
            if k.startswith("projects:")
            or k.startswith("sessions:")
            or k.startswith("global_sessions:")
            or k.startswith("detail:")
        ]
        for k in keys_to_remove:
            self._cache.pop(k, None)
        return len(keys_to_remove)

    @classmethod
    def invalidate_project_caches_across_instances(cls) -> int:
        """Invalidate project/session caches across all live HistoryService instances."""
        removed = 0
        for service in list(cls._instances):
            try:
                removed += service.invalidate_project_caches()
            except Exception:
                logger.debug("Failed to invalidate history caches on a live service instance", exc_info=True)
        return removed

    def _resolve_parser_for_alias(self, alias: str) -> Optional[BaseHistoryParser]:
        """Resolve the parser for an alias by checking known base provider prefixes."""
        # Direct match
        if alias in self._parsers:
            return self._parsers[alias]
        # Check if alias starts with a known provider name (e.g. claude-internal -> claude)
        for provider_name, parser in self._parsers.items():
            if alias.startswith(provider_name):
                return parser
        return None

    async def list_all_sessions(
        self,
        user_home: Path,
        project_path: str,
        alias_config_map: Dict[str, Path],
        provider_filter: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> SessionListResponse:
        """List sessions across all providers/aliases, filtered by project_path.

        Args:
            user_home: User home directory (e.g. /home/bob)
            project_path: Workspace project path to filter by
            alias_config_map: Mapping of alias/provider -> config_path (resolved absolute paths)
            provider_filter: Optional provider name to filter by
            search: Optional search text for session title
            page: Page number (1-based)
            page_size: Page size
        """
        all_sessions: List[SessionMeta] = []

        async def _load_alias_sessions(alias: str, config_path: Path, parser: BaseHistoryParser) -> List[SessionMeta]:
            cache_key = f"sessions:{config_path}:{project_path}:{parser.provider_name}"
            cached = self._get_cached(cache_key)
            if cached is not None:
                return cached
            try:
                sessions = await asyncio.to_thread(
                    parser.list_sessions, config_path, project_path
                )
                for session in sessions:
                    if not session.alias:
                        session.alias = alias
                self._set_cached(cache_key, sessions, ttl=_PROJECTS_CACHE_TTL_SECONDS)
                return sessions
            except Exception as e:
                logger.warning(
                    "Failed to list sessions for alias=%s config_path=%s: %s",
                    alias, config_path, e,
                )
                return []

        tasks: List[asyncio.Future] = []
        for alias, config_path in alias_config_map.items():
            parser = self._resolve_parser_for_alias(alias)
            if parser is None:
                continue
            if provider_filter and parser.provider_name != provider_filter and alias != provider_filter:
                continue
            tasks.append(_load_alias_sessions(alias, config_path, parser))

        if tasks:
            for result in await asyncio.gather(*tasks):
                all_sessions.extend(result or [])

        # Search filter
        if search:
            search_lower = search.lower()
            all_sessions = [s for s in all_sessions if search_lower in s.title.lower()]

        # Sort by updated_at descending
        all_sessions.sort(key=lambda s: s.updated_at, reverse=True)

        total = len(all_sessions)
        start = (page - 1) * page_size
        end = start + page_size
        page_sessions = all_sessions[start:end]

        return SessionListResponse(
            total=total,
            page=page,
            page_size=page_size,
            sessions=page_sessions,
        )

    async def list_global_sessions(
        self,
        alias_config_map: Dict[str, Path],
        provider_filter: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        linux_user: Optional[str] = None,
    ) -> SessionListResponse:
        """List sessions across ALL projects and ALL providers globally.

        Unlike list_all_sessions, this does NOT filter by project_path.
        It calls each parser's list_all_sessions(config_path) to get every
        session, then merges, deduplicates, and sorts by updated_at descending.

        Args:
            alias_config_map: Mapping of alias/provider -> config_path
            provider_filter: Optional provider name to filter by
            search: Optional search text for session title
            page: Page number (1-based)
            page_size: Page size
            linux_user: Optional Linux username to tag on each session
        """
        all_sessions: List[SessionMeta] = []

        async def _load_alias_sessions(alias: str, config_path: Path, parser: BaseHistoryParser) -> List[SessionMeta]:
            cache_key = f"global_sessions:{config_path}:{parser.provider_name}:{linux_user or ''}"
            cached = self._get_cached(cache_key)
            if cached is not None:
                return cached
            try:
                sessions = await asyncio.to_thread(
                    parser.list_all_sessions, config_path, linux_user
                )
                for session in sessions:
                    if not session.alias:
                        session.alias = alias
                    if linux_user and not session.exec_user:
                        session.exec_user = linux_user
                self._set_cached(cache_key, sessions, ttl=_PROJECTS_CACHE_TTL_SECONDS)
                return sessions
            except Exception as e:
                logger.warning(
                    "Failed to list global sessions for alias=%s config_path=%s: %s",
                    alias, config_path, e,
                )
                return []

        tasks: List[asyncio.Future] = []
        for alias, config_path in alias_config_map.items():
            parser = self._resolve_parser_for_alias(alias)
            if parser is None:
                continue
            if provider_filter and parser.provider_name != provider_filter and alias != provider_filter:
                continue
            tasks.append(_load_alias_sessions(alias, config_path, parser))

        if tasks:
            for result in await asyncio.gather(*tasks):
                all_sessions.extend(result or [])

        # Deduplicate by exec_user:provider:session_id (keep the one with latest updated_at)
        merged: Dict[str, SessionMeta] = {}
        for s in all_sessions:
            key = f"{s.exec_user or ''}:{s.provider or ''}:{s.id}"
            prev = merged.get(key)
            if prev is None or (s.updated_at or 0) > (prev.updated_at or 0):
                merged[key] = s
        all_sessions = list(merged.values())

        # Search filter
        if search:
            search_lower = search.lower()
            all_sessions = [s for s in all_sessions if search_lower in s.title.lower()]

        # Sort by updated_at descending
        all_sessions.sort(key=lambda s: s.updated_at, reverse=True)

        total = len(all_sessions)
        start = (page - 1) * page_size
        end = start + page_size
        page_sessions = all_sessions[start:end]

        return SessionListResponse(
            total=total,
            page=page,
            page_size=page_size,
            sessions=page_sessions,
        )

    async def get_session_detail(
        self,
        provider: str,
        config_path: Path,
        session_id: str,
    ) -> Optional[SessionMessagesResponse]:
        """Get session messages and tool calls.

        Args:
            provider: Provider name (to select the right parser)
            config_path: Config directory for this provider/alias
            session_id: Session ID
        """
        parser = self._resolve_parser_for_alias(provider)
        if parser is None:
            return None

        cache_key = f"detail:{config_path}:{session_id}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            detail: Optional[HistorySessionDetail] = await asyncio.to_thread(
                parser.get_session_detail, config_path, session_id
            )
        except Exception as e:
            logger.warning(
                "Failed to get session detail for provider=%s session_id=%s: %s",
                provider, session_id, e,
            )
            return None

        if detail is None:
            return None

        result = SessionMessagesResponse(
            session_id=detail.session_id,
            messages=detail.messages,
            tool_calls=detail.tool_calls,
            session=detail.session,
        )
        self._set_cached(cache_key, result)
        return result

    async def list_projects(
        self,
        alias_config_map: Dict[str, Path],
        provider_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Discover all available project paths across all providers.

        Aggregates results from each parser's list_projects(), merges by path,
        and resolves Gemini hashes against known paths from other providers.

        Returns a list of dicts:
            {
                "path": str,
                "providers": [{"provider": str, "alias": str, "session_count": int}],
                "total_sessions": int,
                "last_active": int,  # ms timestamp
            }
        """
        # Phase 1: Collect projects from all providers (except Gemini hashes)
        path_map: Dict[str, Dict[str, Any]] = {}
        gemini_hashes: List[Dict[str, Any]] = []

        for alias, config_path in alias_config_map.items():
            parser = self._resolve_parser_for_alias(alias)
            if parser is None:
                continue
            if provider_filter and parser.provider_name != provider_filter and alias != provider_filter:
                continue

            cache_key = f"projects:{config_path}:{parser.provider_name}"
            cached = self._get_cached(cache_key)
            if cached is not None:
                entries = cached
            else:
                try:
                    entries = await asyncio.to_thread(parser.list_projects, config_path)
                    self._set_cached(cache_key, entries, ttl=_PROJECTS_CACHE_TTL_SECONDS)
                except Exception as e:
                    logger.warning(
                        "Failed to list projects for alias=%s config_path=%s: %s",
                        alias, config_path, e,
                    )
                    entries = []

            for entry in entries:
                if "hash" in entry and "path" not in entry:
                    # Gemini hash entry — save for Phase 2 matching
                    entry["alias"] = alias
                    gemini_hashes.append(entry)
                    continue

                path = entry["path"]
                if path not in path_map:
                    path_map[path] = {
                        "path": path,
                        "providers": [],
                        "total_sessions": 0,
                        "last_active": 0,
                    }
                path_map[path]["providers"].append({
                    "provider": entry.get("provider", parser.provider_name),
                    "alias": alias,
                    "session_count": entry.get("session_count", 0),
                })
                path_map[path]["total_sessions"] += entry.get("session_count", 0)
                if entry.get("last_active", 0) > path_map[path]["last_active"]:
                    path_map[path]["last_active"] = entry["last_active"]

        # Phase 2: Match Gemini hashes against known project paths
        if gemini_hashes:
            for known_path in list(path_map.keys()):
                path_hash = hashlib.sha256(known_path.encode("utf-8")).hexdigest()
                for gh in gemini_hashes:
                    if gh["hash"] == path_hash:
                        alias = gh.get("alias", "gemini")
                        path_map[known_path]["providers"].append({
                            "provider": "gemini",
                            "alias": alias,
                            "session_count": gh.get("session_count", 0),
                        })
                        path_map[known_path]["total_sessions"] += gh.get("session_count", 0)
                        if gh.get("last_active", 0) > path_map[known_path]["last_active"]:
                            path_map[known_path]["last_active"] = gh["last_active"]
                        gemini_hashes.remove(gh)
                        break

            # Remaining unmatched Gemini hashes — add as unknown entries
            for gh in gemini_hashes:
                alias = gh.get("alias", "gemini")
                path_map[f"[gemini:{gh['hash'][:12]}...]"] = {
                    "path": f"[gemini:{gh['hash'][:12]}...]",
                    "providers": [{
                        "provider": "gemini",
                        "alias": alias,
                        "session_count": gh.get("session_count", 0),
                    }],
                    "total_sessions": gh.get("session_count", 0),
                    "last_active": gh.get("last_active", 0),
                    "gemini_hash": gh["hash"],
                }

        # Sort by last_active descending
        result = sorted(path_map.values(), key=lambda x: x["last_active"], reverse=True)
        return result
