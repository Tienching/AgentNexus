# -*- coding: utf-8 -*-
"""Claude Code API - Stream API wrapper for ccr code CLI

Note: app and metrics should be imported directly from src.server.app to avoid
circular imports. This module exports config and logger utilities only.
"""

__version__ = "0.1.0"

# Export config and logger (no circular dependency)
from .config import settings
from .logger import get_logger, setup_logger

__all__ = [
    "settings",
    "get_logger",
    "setup_logger",
]
