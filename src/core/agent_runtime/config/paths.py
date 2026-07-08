"""Runtime path helpers derived from the active config context."""

from __future__ import annotations

from pathlib import Path

from src.core.agent_runtime.config.loader import get_config_path
from src.core.agent_runtime.utils.helpers import ensure_dir

_NEXUS_HOME = Path.home() / ".nexus"
_LEGACY_HOME = Path.home() / ".nanobot"


def _prefer_new_or_legacy(new_path: Path, legacy_path: Path) -> Path:
    if new_path.exists():
        return new_path
    if legacy_path.exists():
        return legacy_path
    return new_path


def get_data_dir() -> Path:
    """Return the instance-level runtime data directory."""
    return ensure_dir(get_config_path().parent)


def get_runtime_subdir(name: str) -> Path:
    """Return a named runtime subdirectory under the instance data dir."""
    return ensure_dir(get_data_dir() / name)


def get_media_dir(channel: str | None = None) -> Path:
    """Return the media directory, optionally namespaced per channel."""
    base = get_runtime_subdir("media")
    return ensure_dir(base / channel) if channel else base


def get_cron_dir() -> Path:
    """Return the cron storage directory."""
    return get_runtime_subdir("cron")


def get_logs_dir() -> Path:
    """Return the logs directory."""
    return get_runtime_subdir("logs")


def get_workspace_path(workspace: str | None = None) -> Path:
    """Resolve and ensure the agent workspace path."""
    default_path = _prefer_new_or_legacy(_NEXUS_HOME / "workspace", _LEGACY_HOME / "workspace")
    path = Path(workspace).expanduser() if workspace else default_path
    return ensure_dir(path)


def is_default_workspace(workspace: str | Path | None) -> bool:
    """Return whether a workspace resolves to the default workspace path."""
    current = (
        Path(workspace).expanduser()
        if workspace is not None
        else _prefer_new_or_legacy(_NEXUS_HOME / "workspace", _LEGACY_HOME / "workspace")
    )
    default_candidates = [
        _NEXUS_HOME / "workspace",
        _LEGACY_HOME / "workspace",
    ]
    return any(
        current.resolve(strict=False) == candidate.resolve(strict=False)
        for candidate in default_candidates
    )


def get_cli_history_path() -> Path:
    """Return the shared CLI history file path."""
    return _prefer_new_or_legacy(
        _NEXUS_HOME / "history" / "cli_history",
        _LEGACY_HOME / "history" / "cli_history",
    )


def get_bridge_install_dir() -> Path:
    """Return the shared WhatsApp bridge installation directory."""
    return _prefer_new_or_legacy(_NEXUS_HOME / "bridge", _LEGACY_HOME / "bridge")


def get_legacy_sessions_dir() -> Path:
    """Return the legacy global session directory used for migration fallback."""
    return _LEGACY_HOME / "sessions"
