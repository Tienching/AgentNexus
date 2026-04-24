# Collaboration Plane APIs

Agent Nexus now layers project / issue / inbox collaboration APIs on top of raw task storage:

- `GET /api/nexus/collab/projects`
- `GET /api/nexus/collab/projects/{project_id}`
- `GET /api/nexus/collab/issues`
- `GET /api/nexus/collab/issues/{issue_key}`
- `GET /api/nexus/collab/inbox`
- `POST /api/nexus/collab/issues`

The collaboration layer does not replace the underlying task queue. It materializes project and issue read-models from task fields such as `project_id`, `project_name`, `ticket_ref`, and GitHub linkage.
