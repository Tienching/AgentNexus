# -*- coding: utf-8 -*-
"""Hermes AG-UI adapter.

Hermes emits the same stream-json event shape as CodeBuddy/Claude (text deltas,
tool calls, session ids), so the conversion pipeline is shared. This module
aliases the CodeBuddy adapter rather than duplicating ~700 lines; the
CodeBuddy-specific summary stripping is a harmless no-op for Hermes output.
"""

from src.runtime.adapters.codebuddy import CodebuddyAGUIAdapter

HermesAGUIAdapter = CodebuddyAGUIAdapter

__all__ = ["HermesAGUIAdapter"]
