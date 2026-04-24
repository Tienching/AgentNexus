# Operator Automation Surface

Agent Nexus now exposes an operator-facing automation surface with **API parity + CLI coverage** via `scripts/nexusctl.py`.

## CLI resources

```bash
python3 scripts/nexusctl.py dashboard
python3 scripts/nexusctl.py control-plane tenants
python3 scripts/nexusctl.py control-plane workspaces --tenant-id tenant-a
python3 scripts/nexusctl.py control-plane access --username alice --workspace-id ws-a
python3 scripts/nexusctl.py control-plane audit --workspace-id ws-a
python3 scripts/nexusctl.py collab projects
python3 scripts/nexusctl.py collab issues --project-id launch
python3 scripts/nexusctl.py collab inbox --exec-user ubuntu
python3 scripts/nexusctl.py extensions catalog
python3 scripts/nexusctl.py repos registry
python3 scripts/nexusctl.py repos caches
```

## Output contracts

- Default output is stable, pretty-printed JSON for automation.
- `--format table` enables a lightweight terminal dashboard / operator-friendly view.
- Exit code `0` means success.
- Exit code `1` means runtime error and emits a JSON error payload on stderr.
- Exit code `2` means invalid invocation / help path.

## API parity map

| CLI | HTTP API |
| --- | --- |
| `control-plane tenants` | `GET /api/nexus/control-plane/tenants` |
| `control-plane workspaces` | `GET /api/nexus/control-plane/workspaces` |
| `control-plane access` | `GET /api/nexus/control-plane/access` / `GET /api/nexus/control-plane/workspaces/{workspace_id}/access` |
| `control-plane audit` | `GET /api/nexus/control-plane/workspaces/{workspace_id}/audit` |
| `collab projects` | `GET /api/nexus/collab/projects` |
| `collab issues` | `GET /api/nexus/collab/issues` |
| `collab inbox` | `GET /api/nexus/collab/inbox` |
| `extensions catalog` | `GET /api/nexus/extensions/catalog` |
| `repos registry` | repo/worktree registry read model |
| `repos caches` | bare repo cache read model |
| `dashboard` | composite view over control-plane, collaboration, extensions, and repo registry |

## Operator workflows

- Use `dashboard` for a compact terminal overview.
- Use JSON subcommands for automation, scheduled checks, and shell pipelines.
- Use the REST APIs when integrating with external systems or browser clients.
