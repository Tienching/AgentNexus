# -*- coding: utf-8 -*-
"""FastAPI entry re-export."""

from src.server.app import app, metrics

__all__ = ["app", "metrics"]
