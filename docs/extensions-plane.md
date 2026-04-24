# Extension Registry APIs

Agent Nexus now exposes a unified extension registry:

- `GET /api/nexus/extensions/catalog`
- `POST /api/nexus/extensions/skills/import`

The catalog aggregates:

- installed/enabled providers
- runtime plugin directories
- bundled skills shipped in the repository
- provider/alias skills discovered from config directories
- admin/settings panel extension points

`POST /api/nexus/extensions/skills/import` copies a bundled skill into a provider skill directory, giving the product a real skill-import supply path instead of a read-only listing.
