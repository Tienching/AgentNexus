# Unreleased

## User-visible changes

- Added workflow template and pipeline snapshot APIs.
- Added an onboarding/readiness tab in the Nexus settings UI.
- Added SQLite-first metrics and setup readiness checks.

## Operational changes

- CI now has stronger quality gates and a docs freshness workflow.
- UI docs freshness checks now cover screenshot/doc drift more explicitly.

## Verification

- OpenAPI parity test remains in sync with the generated spec.
- Browser smoke coverage now exercises real HTTP + Playwright flows.
- Regression coverage was expanded for the app-scoped service container,
  history provider/alias resolution, legacy history compat resume flows,
  task read-model assembly, and SQLite DB reset/isolation behavior.
