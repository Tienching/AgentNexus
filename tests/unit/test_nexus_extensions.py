# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from src.runtime.stores.db import Database
from src.server.services import reset_app_container


TEST_SAFE_STARTUP_POLICY = {
    "start_task_executor": False,
    "start_task_scheduler": False,
    "start_channel_service": False,
    "start_terminal_manager": False,
    "start_evolution_service": False,
}


