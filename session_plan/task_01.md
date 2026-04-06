Title: Isolate nexus admin startup from ambient settings
Files: src/server/app.py, tests/conftest.py, tests/unit/test_nexus_admin.py
Issue: none

Introduce a test-safe app bootstrap path so admin diagnostics tests do not inherit host configuration at import time. Focus on the FastAPI construction and `lifespan()` entry points in `src/server/app.py`: extract or expose an app-factory/settings-override path that lets tests decide whether required subsystems should start before `TestClient` enters lifespan. Then update `tests/conftest.py` and the `client` fixture in `tests/unit/test_nexus_admin.py` to use that path instead of importing the global app eagerly.

Why: `tests/unit/test_nexus_admin.py` currently fails during startup because the scheduler is marked unhealthy when the executor is disabled by ambient settings. The test should validate `/api/nexus/diagnostics` and `/api/nexus/audit`, not the developer machine's startup configuration.

Verify with: `python3 -m pytest tests/unit/test_nexus_admin.py -q`.
