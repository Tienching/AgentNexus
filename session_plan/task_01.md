Title: Isolate nexus runtimes route tests from startup policy
Files: tests/unit/test_nexus_runtimes.py
Issue: none

Update the `client` fixture in `tests/unit/test_nexus_runtimes.py` to stop importing the shared `app` singleton and instead use `app_factory(startup_policy_overrides=...)`, matching the hermetic pattern already used by `tests/unit/test_nexus_admin.py` and `tests/unit/test_nexus_ops.py`.

Add a regression test that explicitly sets `src.server.app.settings.executor_enabled = False` and `src.server.app.settings.scheduler_enabled = True` to prove `/api/nexus/agent-runtimes` still boots under an isolated startup policy. Keep the existing endpoint assertions focused on route behavior; the fix here is test-fixture isolation, not runtime detection logic.

Verify with:
`python3 -m pytest tests/unit/test_nexus_runtimes.py -q`
