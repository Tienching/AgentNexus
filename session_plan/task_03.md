Title: Surface cron store corruption as degraded service state
Files: src/nanobot/cron/service.py, tests/unit/test_cron_service.py
Issue: none

Tighten `CronService._load_store()` so malformed or incompatible store data does not silently collapse into an apparently healthy empty schedule. Preserve the load failure reason on the service, continue with an empty in-memory `CronStore()`, and expose that degraded state from `CronService.status()` so callers can distinguish "no jobs configured" from "jobs could not be loaded".

Why: today a broken cron store only produces a warning log and then looks identical to an empty store. That hides real operator action items and weakens reliability for scheduled missions.

Add targeted tests in `tests/unit/test_cron_service.py` for invalid JSON or malformed job payloads, plus recovery after the backing file is repaired. Verify with `python3 -m pytest tests/unit/test_cron_service.py -q`.