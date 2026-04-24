# Changelog

All notable changes to Agent Nexus should be documented in this file.

The format is intentionally lightweight:

- `Added` for new product capabilities
- `Changed` for behavior changes and migrations
- `Fixed` for bug fixes
- `Operational` for deploy/runbook/incident-impacting changes

## Unreleased

### Added
- Release discipline pack (`CHANGELOG.md`, `RELEASE.md`, `docs/releases/`).
- App-scoped service container for session storage / history service / task queue.
- Strict migration discovery and OpenAPI parity CI checks.

### Changed
- SQLite migration startup now fails fast when schema verification fails.
- History summary/grouping now reuses the runtime `HistoryService` as the single truth source.
- Dev/test/runtime bootstrap scripts are aligned around `uv sync --extra dev --group dev`.

### Fixed
- Coverage configuration now uses a valid `src` target and enforces a minimum threshold.
- Optional Redis-backed tests are excluded from the default suite unless the extra is installed.

### Operational
- Added a minimal GitHub Actions workflow for lint, regression tests, coverage, and OpenAPI parity.
