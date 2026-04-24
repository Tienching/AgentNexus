# Agents / Settings / Task Shell Migration

## Top-level navigation

The shell now centers on four primary surfaces:

- Chat
- Task
- Agents
- Settings

No standalone `Admin` or `Dashboard` top-level page should remain.

## Legacy route compatibility

Old deep links are normalized as follows:

| Legacy route | New destination |
| --- | --- |
| `?page=project` | `?page=chat` |
| `?page=config` | `?page=settings` |
| `?page=admin` | `?page=settings` |
| `?page=dashboard` | `?page=agents` |

## Settings consolidation

Settings is a single-page surface with three sections:

- `Basic`
- `Extensions`
- `Safety`

### Legacy Settings tab migration

| Legacy tab | New home |
| --- | --- |
| Overview | Settings → Basic |
| Onboarding | Settings → Basic |
| General | Settings → Basic |
| Runtimes | Settings → Basic (advanced) |
| MCP | Settings → Extensions |
| Skills | Settings → Extensions |
| Integrations | Settings → Extensions |
| Security | Settings → Safety |
| Audit | Settings → Safety |
| Cleanup | Settings → Safety |
| Admin / Feature Flags | Settings → Safety (advanced) |
| Tools | context entry points only |
| Search | global search (`Ctrl/Cmd+K`) |

## Task migration

The Task surface owns:

- Board
- Schedules
- Workflows

Scheduling and workflow management should not require opening Settings.

## Agents migration

The Agents surface owns:

- Agents overview
- Agent detail
- Team detail
- Agent-level runtime binding
- Agent-level memory / capabilities / activity

This means the old Settings tabs for `Agents`, `Activity`, and `Memory` are removed from the primary settings flow.

## Visual regression test data cleanup

Browser and UI regression tests should use clearly prefixed fixture data and clean it within the isolated test app lifecycle whenever possible.

Recommended prefixes:

- `browser-`
- `agents-e2e-`
- `task-surface-`

If manual cleanup is needed in a shared local database, clear only synthetic records whose user, title, or description match those prefixes before re-running visual tests.
