Title: Remove evolution router dependence on private service state
Files: src/server/services/evolution_service.py, src/server/routers/nexus_evolution.py, tests/unit/test_nexus_evolution.py
Issue: none

Add public inspection methods on `EvolutionService` and convert the evolution router to typed responses that no longer read `_lock` or `_config` directly.

Why: `src/server/routers/nexus_evolution.py` currently depends on private attributes for concurrency checks and memory previews. That couples the HTTP layer to service internals and makes status/memory endpoints fragile.

Change:
- In `src/server/services/evolution_service.py`, expose public helpers for "is evolution running" and for reading memory preview content safely.
- In `src/server/routers/nexus_evolution.py`, add response models for trigger, synthesis, status, and memory endpoints and switch the handlers to those public helpers.
- Add tests in `tests/unit/test_nexus_evolution.py` for the 409 path, success payloads, and memory preview behavior.

Verify with `python3 -m pytest tests/unit/test_nexus_evolution.py -q`.