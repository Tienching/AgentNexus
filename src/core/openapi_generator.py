# -*- coding: utf-8 -*-
"""OpenAPI 3.1 specification generator.

Generates a complete OpenAPI 3.1 specification for the Nexus API
and saves it to docs/openapi.json.

Usage:
    python -m src.core.openapi_generator
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.server.app import create_app


def generate_openapi_spec() -> dict:
    """Generate OpenAPI 3.1 spec from the FastAPI app."""
    app = create_app()
    spec = app.openapi_schema

    if spec is None:
        # Force generation if not set
        spec = app.openapi()

    # Upgrade to OpenAPI 3.1 if needed
    if spec.get("openapi") and spec["openapi"].startswith("3.0"):
        spec["openapi"] = "3.1.0"

    # Add info
    spec["info"] = {
        "title": "Nexus Agent Management API",
        "description": """
## Overview

Nexus is an AI agent management platform that provides:

- **Agent Lifecycle Management** - Register, heartbeat, and monitor agents
- **Task Queue & Scheduling** - Priority-based task queue with cron scheduling
- **Session Management** - Conversation sessions with message chain tracking
- **Observability** - SQLite-first health/metrics snapshots with optional Redis compatibility
- **Setup Readiness** - Guided onboarding checks for CLI/runtime/workspace prerequisites
- **Feature Flags** - Progressive feature rollout

## Authentication

Most endpoints require authentication via the `Authorization` header:

```
Authorization: Bearer <token>
```

## Rate Limits

- Standard: 100 requests/minute
- Authenticated: 1000 requests/minute
        """,
        "version": "1.0.0",
        "contact": {
            "name": "Nexus Support",
        },
        "license": {
            "name": "MIT",
        },
    }

    # Add server information
    spec["servers"] = [
        {
            "url": "/api",
            "description": "Local API server",
        },
    ]

    # Add tags for organization
    spec["tags"] = [
        {"name": "agents", "description": "Agent lifecycle management"},
        {"name": "tasks", "description": "Task queue and management"},
        {"name": "sessions", "description": "Conversation session management"},
        {"name": "schedules", "description": "Cron scheduling"},
        {"name": "runs", "description": "Task execution runs"},
        {"name": "history", "description": "Session history and search"},
        {"name": "admin", "description": "Admin and observability endpoints"},
        {"name": "auth", "description": "Authentication"},
        {"name": "security", "description": "Security and permissions"},
        {"name": "features", "description": "Feature flags"},
        {"name": "evolution", "description": "Agent evolution system"},
    ]

    return spec


def main():
    """Generate and save the OpenAPI spec."""
    spec = generate_openapi_spec()

    output_path = Path(__file__).parent.parent.parent / "docs" / "openapi.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        json.dump(spec, f, indent=2)

    print(f"OpenAPI spec generated: {output_path}")
    print(f"  - {len(spec.get('paths', {}))} paths")
    print(f"  - {sum(len(v) for v in spec.get('components', {}).get('schemas', {}).values())} schemas")


if __name__ == "__main__":
    main()
