# -*- coding: utf-8 -*-
"""Base history parser abstract class and shared utilities."""

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Generator, List, Optional

from ..models.session import SessionMeta, StoredMessage, StoredToolCall

logger = logging.getLogger(__name__)

# Maximum lines to read from a single JSONL file (safety limit)
MAX_JSONL_LINES = 50_000


@dataclass
class HistorySessionDetail:
    """Parsed session detail containing messages and tool calls."""
    session_id: str
    messages: List[StoredMessage] = field(default_factory=list)
    tool_calls: List[StoredToolCall] = field(default_factory=list)
    session: Optional[SessionMeta] = None


class BaseHistoryParser(ABC):
    """Abstract base class for history parsers.

    Each concrete parser reads a specific provider's native session files
    and converts them to the project's unified data models.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider name (e.g. 'claude', 'codex', 'codebuddy', 'gemini')."""
        ...

    @abstractmethod
    def list_sessions(self, config_path: Path, project_path: str) -> List[SessionMeta]:
        """List sessions from the provider's data directory filtered by project_path.

        Args:
            config_path: Provider config directory (e.g. ~/.claude or ~/.claude-internal)
            project_path: Workspace project path to filter by (e.g. /home/bob/myproject)

        Returns:
            List of SessionMeta with source="history"
        """
        ...

    @abstractmethod
    def get_session_detail(self, config_path: Path, session_id: str) -> Optional[HistorySessionDetail]:
        """Get full session detail (messages + tool calls) for a specific session.

        Args:
            config_path: Provider config directory
            session_id: Session ID to retrieve

        Returns:
            HistorySessionDetail or None if not found
        """
        ...

    def list_projects(self, config_path: Path) -> List[Dict[str, object]]:
        """Discover available project paths from the provider's data directory.

        Returns a list of dicts with at least:
            - path: str — decoded project path (e.g. /home/bob/myproject)
            - provider: str — provider name
            - session_count: int — number of sessions found
            - last_active: int — latest session timestamp in ms

        Default implementation returns an empty list.
        Parsers that can discover projects should override this.
        """
        return []

    def list_all_sessions(self, config_path: Path, linux_user: Optional[str] = None) -> List[SessionMeta]:
        """List ALL sessions across all projects (no project_path filter).

        Default implementation: enumerate projects via list_projects(), then
        call list_sessions() for each discovered project path.
        Subclasses can override for more efficient implementations.

        Args:
            config_path: Provider config directory (e.g. ~/.claude)
            linux_user: Optional Linux username to tag on each session

        Each returned SessionMeta will have exec_dir set to the project path
        and exec_user set to linux_user if provided.
        """
        all_sessions: List[SessionMeta] = []
        try:
            projects = self.list_projects(config_path)
        except Exception as e:
            logger.warning("list_all_sessions: list_projects failed for %s: %s", config_path, e)
            return []

        for proj in projects:
            project_path = proj.get("path")
            if not project_path or not isinstance(project_path, str):
                continue
            try:
                sessions = self.list_sessions(config_path, project_path)
                for s in sessions:
                    if not s.exec_dir:
                        s.exec_dir = project_path
                    if linux_user and not s.exec_user:
                        s.exec_user = linux_user
                all_sessions.extend(sessions)
            except Exception as e:
                logger.warning(
                    "list_all_sessions: list_sessions failed for %s project=%s: %s",
                    self.provider_name, project_path, e,
                )
        return all_sessions

    # ---- Shared Utilities ----

    @staticmethod
    def safe_read_jsonl(file_path: Path, max_lines: int = MAX_JSONL_LINES) -> Generator[dict, None, None]:
        """Read a JSONL file line by line, yielding parsed dicts.

        Skips malformed lines and enforces a max line count.
        """
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f):
                    if i >= max_lines:
                        logger.warning(
                            "JSONL file %s exceeded %d lines, truncating", file_path, max_lines
                        )
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue
        except OSError as e:
            logger.warning("Failed to read JSONL file %s: %s", file_path, e)

    @staticmethod
    def encode_project_path(project_path: str) -> str:
        """Encode a project path to Claude's directory name format.

        /home/bob/myproject -> -home-bob-myproject
        """
        return project_path.replace("/", "-")

    @staticmethod
    def normalize_path(path_str: str) -> str:
        """Normalize a path string for comparison (resolve, strip trailing slash)."""
        return str(Path(path_str).resolve()).rstrip("/")


def decode_encoded_project_path(segments: List[str], leading_slash: bool = True) -> Optional[str]:
    """Decode a dash-encoded project path back to the original filesystem path.

    Both Claude and CodeBuddy encode project paths by replacing '/' with '-'.
    This creates ambiguity because literal '-' in dir names also becomes '-'.

    Uses DFS with memoization: at each '-' boundary, try both interpretations
    ('/' = path separator, '-' = literal dash in name) and return the result
    that corresponds to an existing filesystem path.

    Args:
        segments: List of path segments split by '-'
        leading_slash: If True, path starts with '/'

    Returns:
        The decoded filesystem path, or a naive fallback.
    """
    if not segments:
        return None

    n = len(segments)

    def _find(idx: int, current_component: str, path_so_far: str) -> Optional[str]:
        """Recursive finder.

        idx: next segment index to consume
        current_component: the current directory-name component being built
        path_so_far: the path built so far (ends with current_component)
        """
        if idx >= n:
            # All segments consumed, return this path
            return path_so_far

        seg = segments[idx]

        # Option A: treat this '-' as a literal dash → extend current component
        dash_component = current_component + "-" + seg
        dash_path = path_so_far + "-" + seg

        # Option B: treat this '-' as '/' → start new path component
        slash_path = path_so_far + "/" + seg

        # Try option B (slash) first — if the directory up to path_so_far exists
        result_slash = None
        result_dash = None

        if Path(path_so_far).is_dir():
            result_slash = _find(idx + 1, seg, slash_path)
            if result_slash and Path(result_slash).exists():
                return result_slash  # Found an existing path, return immediately

        # Try option A (dash) — continue building the same component
        result_dash = _find(idx + 1, dash_component, dash_path)
        if result_dash and Path(result_dash).exists():
            return result_dash

        # Neither produced an existing path — return whichever we have
        if result_slash:
            return result_slash
        return result_dash

    start = "/" + segments[0]
    return _find(1, segments[0], start)
