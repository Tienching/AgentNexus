# -*- coding: utf-8 -*-
"""Nexus API Router — composite of domain-specific sub-routers.

This module assembles all Nexus API sub-routers into a single composite
router that is included by app.py.  Individual route implementations live
in their respective domain modules:

- nexus_sessions.py  — Session CRUD, bulk operations, cancel
- nexus_tasks.py     — Task CRUD, bulk operations, continue
- nexus_files.py     — Session file list / download
- nexus_streaming.py — AG-UI SSE streaming endpoints
- nexus_skills.py    — Skills discovery / CRUD
- nexus_config.py    — Server defaults + concurrency config
- nexus_models.py    — Shared Pydantic models and helpers
"""

from __future__ import annotations

from fastapi import APIRouter

# Domain sub-routers (each defines its own prefix, tags, and auth deps)
from .nexus_sessions import router as sessions_router
from .nexus_tasks import router as tasks_router
from .nexus_files import router as files_router
from .nexus_streaming import router as streaming_router
from .nexus_skills import router as skills_router
from .nexus_config import router as config_router
from .nexus_control_plane import router as control_plane_router
from .nexus_collaboration import router as collaboration_router
from .nexus_extensions import router as extensions_router
from .nexus_operator import router as operator_router

# Composite router — app.py includes this single router
router = APIRouter()

for _sub_router in (
    sessions_router,
    tasks_router,
    files_router,
    streaming_router,
    skills_router,
    config_router,
    control_plane_router,
    collaboration_router,
    extensions_router,
    operator_router,
):
    router.include_router(_sub_router)
