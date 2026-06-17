# -*- coding: utf-8 -*-
"""Provider registry — the single source of truth for provider identity.

Everything that needs to know "which providers exist" imports from here.
Before this module, the provider set was duplicated in six places
(dispatcher.py, alias_registry.py, agent_runtimes.py, install.py,
app.js, process_manager.py) and drifted out of sync. Add or remove a
provider by editing the tables below; the rest of the codebase reads
from them.

This module is deliberately import-free (no db, no settings) so it can be
imported from anywhere without risking a circular import.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, Tuple

# ---------------------------------------------------------------------------
# Canonical providers
# ---------------------------------------------------------------------------
# The chat-provider families the runtime can dispatch to. A provider earns a
# spot here when it has both an executor (src/providers/<name>/) and an AG-UI
# adapter (src/runtime/adapters/<name>/). Aliases (e.g. "claude-internal")
# are NOT members — see ALIASES below.
KNOWN_PROVIDERS: FrozenSet[str] = frozenset({"claude", "codex", "gemini", "codebuddy", "hermes", "openclaw"})

# Fallback when a request arrives with no/unknown provider. The dispatcher and
# both settings mixins (ServerSettings, ProviderSettings) read this so the
# default can never drift between them.
DEFAULT_PROVIDER: str = "claude"

# ---------------------------------------------------------------------------
# Aliases
# ---------------------------------------------------------------------------
# Alias -> canonical provider. Built-in aliases are always resolvable without
# explicit registration. Keys are lowercase. Mirrors AliasRegistry.BUILTIN
# (which keeps its own copy for the SQLite/Redis layer but is sourced here).
ALIASES: Dict[str, str] = {
    "claude": "claude",
    "claude-internal": "claude",
    "codex": "codex",
    "codex-internal": "codex",
    "gemini": "gemini",
    "gemini-internal": "gemini",
    "codebuddy": "codebuddy",
    "hermes": "hermes",
    "openclaw": "openclaw",
}

# Providers whose CLI accepts --input-format stream-json for persistent
# multi-turn execution. This is a *capability* flag, not membership, so it
# lives next to the identity tables rather than being re-derived elsewhere.
STREAM_INPUT_PROVIDERS: FrozenSet[str] = frozenset({"claude", "codebuddy", "claude-internal"})

# ---------------------------------------------------------------------------
# Detection metadata
# ---------------------------------------------------------------------------
# The daemon/provider-discovery layer uses this to find and describe each
# provider on a host. "binaries" is the ordered list of CLI names to probe
# (shutil.which). Keep in sync with KNOWN_PROVIDERS — every canonical
# provider must have an entry here.
PROVIDER_META: Tuple[Dict[str, object], ...] = (
    {
        "id": "claude",
        "name": "Claude Code",
        "description": "Anthropic CLI agent for software engineering tasks.",
        "binaries": ["claude"],
        "auth_required": True,
        "auth_hint": 'Run "claude login" after install to authenticate.',
        "version_flag": "--version",
    },
    {
        "id": "codex",
        "name": "Codex CLI",
        "description": "OpenAI CLI agent for code generation and editing.",
        "binaries": ["codex"],
        "auth_required": True,
        "auth_hint": 'Run "codex auth" after install to authenticate.',
        "version_flag": "--version",
    },
    {
        "id": "gemini",
        "name": "Gemini CLI",
        "description": "Google CLI agent for code tasks.",
        "binaries": ["gemini"],
        "auth_required": True,
        "auth_hint": "Set GEMINI_API_KEY in environment to authenticate.",
        "version_flag": "--version",
    },
    {
        "id": "codebuddy",
        "name": "CodeBuddy",
        "description": "Multi-model CLI agent with tool use.",
        "binaries": ["codebuddy"],
        "auth_required": True,
        "auth_hint": "Configure API keys in CodeBuddy settings.",
        "version_flag": "--version",
    },
    {
        "id": "hermes",
        "name": "Hermes",
        "description": "Hermes tool-calling agent CLI (stream-json).",
        "binaries": ["hermes"],
        "auth_required": True,
        "auth_hint": 'Run "hermes login" after install to authenticate.',
        "version_flag": "--version",
    },
    {
        "id": "openclaw",
        "name": "OpenClaw",
        "description": "OpenClaw agent CLI (agent-bound model, stream-json).",
        "binaries": ["openclaw"],
        "auth_required": True,
        "auth_hint": 'Run "openclaw auth" after install to authenticate.',
        "version_flag": "--version",
    },
)
