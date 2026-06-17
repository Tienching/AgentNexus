# -*- coding: utf-8 -*-
"""Hermes Provider

Hermes CLI (https://github.com/) integration. Hermes is a tool-calling agent
that speaks stream-json over stdout, like CodeBuddy/Claude. This executor runs
`hermes chat -q <prompt> -Q` (quiet, non-interactive) and yields its stream-json
output line by line.
"""

from .cli_executor import HermesCLIExecutor, HermesExecutorConfig

__all__ = [
    "HermesCLIExecutor",
    "HermesExecutorConfig",
]
