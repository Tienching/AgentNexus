Title: Surface startup subsystem failures in /health
Files: src/server/app.py, src/server/routers/health.py, tests/unit/test_health_checks.py
Issue: none

Record executor, scheduler, channel service, terminal manager, and evolution service startup outcomes during the FastAPI lifespan, then include those states in the structured /health response.

Why: the app currently logs partial boot failures and keeps serving, but /health only reports Redis, memory, and disk. That can mark the system healthy while core orchestration subsystems are down.

Change:
- In `src/server/app.py`, persist per-subsystem startup state on `app.state` as each component initializes or fails.
- In `src/server/routers/health.py`, add health checks that read those startup states and downgrade the overall status when a required subsystem failed to start.
- Keep the payload structured so mission-control can see which subsystem is degraded and why.

Verify with targeted tests for healthy and failed startup states in `tests/unit/test_health_checks.py`, then run `python3 -m pytest tests/unit/test_health_checks.py -q`.