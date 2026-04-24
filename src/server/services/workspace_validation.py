# -*- coding: utf-8 -*-
"""Workspace path normalization helpers for user-supplied task/schedule inputs."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def normalize_workspace_path(workspace: Optional[str], *, base_dir: Optional[str | Path] = None) -> Optional[str]:
    """Normalize a user-supplied workspace path.

    - Empty values return ``None``.
    - ``~`` is expanded.
    - Relative paths are resolved against ``base_dir`` (or the server cwd).
    - The final path must exist and be a directory.
    """

    raw_value = str(workspace or "").strip()
    if not raw_value:
        return None

    candidate = Path(raw_value).expanduser()
    if not candidate.is_absolute():
        root = Path(base_dir or os.getcwd()).expanduser().resolve(strict=False)
        candidate = root / candidate

    resolved = candidate.resolve(strict=False)
    if not resolved.exists() or not resolved.is_dir():
        raise ValueError(f"workspace 不存在或不是目录: {raw_value}（解析为 {resolved}）")

    return str(resolved)
