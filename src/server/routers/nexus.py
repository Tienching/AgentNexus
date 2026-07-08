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
- nexus_runtimes.py  — Runtime detection / daemon registry
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
from .nexus_admin import router as admin_router
from .nexus_ops import router as ops_router
from .nexus_utils import router as utils_router
from .nexus_runtimes import router as runtimes_router
from .nexus_schedules import router as schedules_router
from .nexus_permissions import router as permissions_router
from .nexus_security import router as security_router
from .nexus_teleport import router as teleport_router
from .nexus_extensions import router as extensions_router
from .nexus_agent_templates import router as agent_templates_router
from .nexus_features import router as features_router
from .nexus_events import router as events_router
from .nexus_system import router as system_router

# Composite router — app.py includes this single router
router = APIRouter()

for _sub_router in (
    sessions_router,
    tasks_router,
    files_router,
    streaming_router,
    skills_router,
    config_router,
    admin_router,
    ops_router,
    utils_router,
    runtimes_router,
    schedules_router,
    permissions_router,
    security_router,
    teleport_router,
    extensions_router,
    agent_templates_router,
    features_router,
    events_router,
    system_router,
):
    router.include_router(_sub_router)
