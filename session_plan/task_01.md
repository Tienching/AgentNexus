Title: Replace deprecated FastAPI 422 constants
Files: src/server/routers/chat.py, src/server/app.py, src/server/services/stream_handler.py
Issue: none

Replace the deprecated `status.HTTP_422_UNPROCESSABLE_ENTITY` constant with the supported FastAPI/Starlette 422 constant everywhere it is still used. Update `_upgrade_legacy_request()` in `src/server/routers/chat.py`, `validation_exception_handler()` in `src/server/app.py`, and `StreamHandler.handle_agui_request()` in `src/server/services/stream_handler.py` so the server stops emitting deprecation warnings during normal validation flows.

Why: Day 3 assessment found the warning in active request paths. This is a small, low-risk cleanup that keeps health/error reporting noise-free and aligns the API layer with current FastAPI behavior.

Verify with:
`python3 -m pytest tests/integration/test_stream.py -q`
Then run:
`python3 -m pytest tests/ -x -q --tb=short`
