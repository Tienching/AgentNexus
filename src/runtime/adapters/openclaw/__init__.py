# -*- coding: utf-8 -*-
"""OpenClaw AG-UI adapter.

OpenClaw's `--json` agent mode emits stream-json events compatible with the
CodeBuddy/Claude pipeline, so the conversion is shared via an alias.
"""

from src.runtime.adapters.codebuddy import CodebuddyAGUIAdapter

OpenClawAGUIAdapter = CodebuddyAGUIAdapter

__all__ = ["OpenClawAGUIAdapter"]
