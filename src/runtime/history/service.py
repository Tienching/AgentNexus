# -*- coding: utf-8 -*-
"""History service — aggregates parsers and provides unified query interface."""

import asyncio
import hashlib
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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

    def __init__(self):
        self._parsers: Dict[str, BaseHistoryParser] = {}
        self._cache: Dict[str, _CacheEntry] = {}

    def register_parser(self, parser: BaseHistoryParser) -> None:
        """Register a history parser by its provider name."""
        self._parsers[parser.provider_name] = parser

    def get_parser(self, provider: str) -> Optional[BaseHistoryParser]:
        """Get a parser by provider name."""
        return self._parsers.get(provider)

    def _get_cached(self, key: str) -> Optional[Any]:
        entry = self._cache.get(key)
        if entry is None or entry.expired:
            self._cache.pop(key, None)
            return None
        return entry.value

    def _set_cached(self, key: str, value: Any, ttl: float = _CACHE_TTL_SECONDS) -> None:
        self._cache[key] = _CacheEntry(value, ttl=ttl)

    def invalidate_project_caches(self) -> int:
        """Invalidate all project-list and session-list caches.

        Called after a CLI execution completes so that the History UI
        immediately reflects updated file timestamps.

        Returns:
            Number of cache entries removed.
        """
        keys_to_remove = [k for k in self._cache if k.startswith("projects:") or k.startswith("sessions:")]
        for k in keys_to_remove:
            self._cache.pop(k, None)
        return len(keys_to_remove)

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

        for alias, config_path in alias_config_map.items():
            parser = self._resolve_parser_for_alias(alias)
            if parser is None:
                continue
            if provider_filter and parser.provider_name != provider_filter and alias != provider_filter:
                continue

            cache_key = f"sessions:{config_path}:{project_path}:{parser.provider_name}"
            cached = self._get_cached(cache_key)
            if cached is not None:
                sessions = cached
            else:
                try:
                    sessions = await asyncio.to_thread(
                        parser.list_sessions, config_path, project_path
                    )
                    # Tag alias on each session
                    for s in sessions:
                        if not s.alias:
                            s.alias = alias
                    self._set_cached(cache_key, sessions, ttl=_PROJECTS_CACHE_TTL_SECONDS)
                except Exception as e:
                    logger.warning(
                        "Failed to list sessions for alias=%s config_path=%s: %s",
                        alias, config_path, e,
                    )
                    sessions = []

            all_sessions.extend(sessions)

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
