Title: Align packaging metadata with the tested source tree
Files: pyproject.toml, pytest.ini, tests/unit/test_project_metadata.py
Issue: none

Repair the metadata drift called out in the assessment so installs and quality gates describe the code that actually exists. In `pyproject.toml`, align `requires-python` with the supported interpreter floor confirmed by the passing test run, remove nonexistent `src/core` and `src/protocols` entries from the wheel/coverage configuration, and add missing core packages such as `src/nanobot` where appropriate. In `pytest.ini`, keep the active pytest defaults aligned with the authoritative test command so config does not silently live only under ignored pyproject settings. Add `tests/unit/test_project_metadata.py` to assert that configured package/source paths exist and that the declared Python floor matches the supported runtime policy. Verify with `python3 -m pytest tests/unit/test_project_metadata.py -q`.
