Title: Hermetic nexus_ops route tests
Files: tests/unit/test_nexus_ops.py
Issue: none

Replace the client fixture in `tests/unit/test_nexus_ops.py` so it uses `app_factory()` instead of importing the shared global `app`. Mirror the startup isolation pattern already used in `tests/unit/test_nexus_admin.py`: define a local `TEST_SAFE_STARTUP_POLICY` that disables the executor, scheduler, channel service, terminal manager, and evolution service, then build `TestClient(app_factory(startup_policy_overrides=...))`.

Add a focused regression assertion that ambient startup settings do not leak into these route tests — for example, patch `src.server.app.settings.executor_enabled` and `src.server.app.settings.scheduler_enabled` into a broken combination and confirm `/api/nexus/search` still responds successfully with auth. The goal is to keep `TestGlobalSearch::test_returns_200` testing the endpoint, not global process startup.

Verify with:
`python3 -m pytest tests/unit/test_nexus_ops.py -q`
