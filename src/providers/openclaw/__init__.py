# -*- coding: utf-8 -*-
"""OpenClaw Provider

OpenClaw CLI integration. OpenClaw binds its model at agent-registration time
(`openclaw agents add --model`), so the executor does not pass `--model`
per-task; it runs `openclaw agent <prompt>` in JSON mode and yields stream-json.

NOTE: OpenClaw is not yet installed in this environment; the executor follows
the documented `openclaw agent` contract (multica server/pkg/agent/openclaw.go
and the reference repo at ~/Projects/openclaw). When the CLI is installed the
per-task wrapper config (OPENCLAW_CONFIG_PATH) is synthesized by the daemon
layer in Phase 4.
"""

from .cli_executor import OpenClawCLIExecutor, OpenClawExecutorConfig

__all__ = [
    "OpenClawCLIExecutor",
    "OpenClawExecutorConfig",
]
