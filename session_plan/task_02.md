Title: Fix Codebuddy timeout cleanup warning
Files: src/providers/codebuddy/cli_executor.py, tests/unit/test_codebuddy_executor_timeout.py
Issue: none

Harden the timeout path in `CodebuddyCLIExecutor._execute_internal()` so subprocess cleanup works with both real processes and async mocks. In particular, make the timeout branch safely handle `kill()` implementations that may be sync or awaitable, and ensure the process is fully waited/drained before returning the JSON timeout event.

Add a narrow regression test in `tests/unit/test_codebuddy_executor_timeout.py` that drives the timeout branch with async mocks and asserts the generator yields the timeout error without triggering unawaited-coroutine warnings.

Why: the current timeout cleanup produces a runtime warning during the test suite, which weakens trust in provider executor behavior.

Verify with:
`python3 -m pytest tests/unit/test_codebuddy_executor_timeout.py -q`