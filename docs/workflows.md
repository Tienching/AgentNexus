# Workflow Templates and Run Snapshots

Agent Nexus now exposes a lightweight workflow layer between single tasks and
the heavier mission DAG surface.

## What is available

- **Workflow templates** — reusable entries that point at a registered pipeline
- **Pipelines** — in-process step sequences with per-step status tracking
- **Run snapshots** — serialized output for inspection and retry

## API surface

- `GET /api/nexus/workflow/templates`
- `GET /api/nexus/workflow/pipelines`
- `GET /api/nexus/workflow/runs`
- `POST /api/nexus/workflow/templates/{template_name}/run`
- `POST /api/nexus/workflow/pipelines/{pipeline_name}/run`
- `POST /api/nexus/workflow/runs/{run_id}/retry`

## Notes

- The current implementation is intentionally lightweight and process-local.
- Each run returns a full JSON snapshot so the UI can render history without
  depending on provider-specific stream formats.
- The default catalogue includes a task intake template and a release-note
  template as examples.
