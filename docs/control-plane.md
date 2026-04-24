# Control Plane APIs

Agent Nexus now exposes first-class tenant / workspace control-plane resources:

- `POST /api/nexus/control-plane/tenants`
- `GET /api/nexus/control-plane/tenants`
- `POST /api/nexus/control-plane/workspaces`
- `GET /api/nexus/control-plane/workspaces`
- `PUT /api/nexus/control-plane/tenants/{tenant_id}/memberships/{username}`
- `PUT /api/nexus/control-plane/workspaces/{workspace_id}/memberships/{username}`
- `GET /api/nexus/control-plane/workspaces/{workspace_id}/access`
- `GET /api/nexus/control-plane/workspaces/{workspace_id}/audit`

These endpoints are backed by SQLite tables in `ControlPlaneService` and emit domain events for audit/read-model use.
