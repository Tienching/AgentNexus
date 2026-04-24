# Release Discipline

This repository uses a lightweight release pack so product, runtime, and ops
changes ship together.

## Before cutting a release

1. Update `CHANGELOG.md`
   - Move relevant `Unreleased` entries into a dated/versioned section.
   - Call out breaking changes and migrations explicitly.
2. Refresh generated artifacts
   - `python -m src.core.openapi_generator`
   - Re-run focused UI/API regression tests.
3. Confirm deploy/runtime notes
   - Schema migrations required?
   - New env vars / credentials?
   - Workspace/history compatibility impacts?
4. Update `docs/releases/`
   - Add a short release note for operators and reviewers.

## Release note checklist

- Version / date
- User-visible features
- Bug fixes
- Required migrations / backfills
- Rollout or rollback notes
- Observability / health changes

## Suggested commands

```bash
./scripts/test.sh all
python -m src.core.openapi_generator
pytest -q tests/unit/test_openapi_parity.py
```
