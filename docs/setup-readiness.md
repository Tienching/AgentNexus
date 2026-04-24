# Setup / Onboarding Readiness

The Nexus UI includes an onboarding tab that summarizes whether the current
environment is ready to run tasks.

## Readiness checks

- SQLite database connectivity
- Provider CLI availability
- Execution user home directory
- Optional Redis configuration

## API surface

- `GET /api/nexus/setup/readiness`

## Interpretation

- `ready: true` means all required checks passed.
- `warning` checks are informational and do not block startup.
- `blocked` checks require action before the UI is fully ready.

## Operator guidance

If setup is blocked:

1. Fix SQLite/database permissions
2. Install or configure the provider CLI
3. Confirm the execution user home exists
4. Re-run the readiness check from the UI or API
