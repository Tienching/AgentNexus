Title: Codify startup failure policy for required subsystems
Files: src/server/app.py, tests/unit/test_health_checks.py, tests/integration/test_api.py
Issue: none

Turn the current startup behavior into an explicit contract. In `src/server/app.py`, add a single policy check near the end of `lifespan()` that evaluates `app.state.startup_subsystems` after initialization and decides whether the process may continue when a required subsystem is unhealthy.

Keep the rule simple: if a subsystem is truly optional, mark it optional when recording startup state; if it is required, fail startup loudly instead of leaving the API running in an implicit degraded mode. That keeps `/health` reporting and actual boot behavior aligned.

Update tests to lock the contract in place. Extend `tests/unit/test_health_checks.py` so health aggregation still reflects required-vs-optional startup states, and add or update an API-level test in `tests/integration/test_api.py` that verifies the app surface matches the chosen startup policy.

Verify with: `python3 -m pytest tests/unit/test_health_checks.py tests/integration/test_api.py -q`.
