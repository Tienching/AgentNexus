Title: Reuse runtime version in API health surfaces
Files: src/server/app.py, src/server/routers/health.py, tests/unit/test_health_checks.py
Issue: none

Remove one slice of duplicated version metadata by making the FastAPI app and `/health` responses read from `src.runtime.__version__` instead of repeating `0.1.0` inline. Update the `FastAPI(...)` declaration in `src/server/app.py` and both `HealthResponse` constructors in `src/server/routers/health.py`, then extend `tests/unit/test_health_checks.py` so the reported version is asserted against the runtime package version rather than a copied literal. Verify with `python3 -m pytest tests/unit/test_health_checks.py -q`.
