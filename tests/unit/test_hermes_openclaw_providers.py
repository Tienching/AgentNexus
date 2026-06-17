# -*- coding: utf-8 -*-
"""Unit tests for the hermes/openclaw providers added in Phase 3."""

from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# registry identity
# ---------------------------------------------------------------------------

def test_registry_knows_hermes_and_openclaw():
    from src.providers.registry import KNOWN_PROVIDERS, PROVIDER_META, ALIASES
    assert {"hermes", "openclaw"} <= KNOWN_PROVIDERS
    ids = {m["id"] for m in PROVIDER_META}
    assert {"hermes", "openclaw"} <= ids
    # every canonical provider must have meta (consistency gate)
    assert KNOWN_PROVIDERS == ids
    assert ALIASES["hermes"] == "hermes"
    assert ALIASES["openclaw"] == "openclaw"


def test_provider_meta_has_required_fields():
    from src.providers.registry import PROVIDER_META
    by_id = {m["id"]: m for m in PROVIDER_META}
    for key in ("hermes", "openclaw"):
        m = by_id[key]
        assert m["name"] and m["binaries"] and m["auth_required"] is True
        assert m["version_flag"] == "--version"


# ---------------------------------------------------------------------------
# dispatcher routing
# ---------------------------------------------------------------------------

class TestDispatcherRouting:
    def test_normalize_canonical(self):
        from src.providers.dispatcher import normalize_provider
        assert normalize_provider("hermes") == "hermes"
        assert normalize_provider("openclaw") == "openclaw"
        assert normalize_provider("Hermes") == "hermes"
        assert normalize_provider("OPENCLAW") == "openclaw"

    def test_create_executor_hermes(self):
        from src.providers.dispatcher import create_executor
        from src.providers.hermes import HermesCLIExecutor
        ex = create_executor("hermes")
        assert isinstance(ex, HermesCLIExecutor)

    def test_create_executor_openclaw(self):
        from src.providers.dispatcher import create_executor
        from src.providers.openclaw import OpenClawCLIExecutor
        ex = create_executor("openclaw")
        assert isinstance(ex, OpenClawCLIExecutor)

    def test_create_adapter_hermes(self):
        from src.providers.dispatcher import create_adapter
        from src.runtime.adapters.codebuddy import CodebuddyAGUIAdapter
        assert isinstance(create_adapter("hermes"), CodebuddyAGUIAdapter)

    def test_create_adapter_openclaw(self):
        from src.providers.dispatcher import create_adapter
        from src.runtime.adapters.codebuddy import CodebuddyAGUIAdapter
        assert isinstance(create_adapter("openclaw"), CodebuddyAGUIAdapter)

    def test_all_executors_includes_new_providers(self):
        from src.providers.dispatcher import create_all_executors
        ex = create_all_executors()
        assert {"hermes", "openclaw"} <= set(ex)


# ---------------------------------------------------------------------------
# executor command building
# ---------------------------------------------------------------------------

class TestHermesCommand:
    def test_builds_chat_quiet_command(self):
        from src.providers.hermes import HermesCLIExecutor
        from src.providers.base import RequestContext
        ex = HermesCLIExecutor()
        ctx = RequestContext(
            session_id="s1", exec_user="u", content="hello world", provider="hermes"
        )
        cmd = ex._build_command(ctx)
        assert cmd[0] == "hermes"
        assert "chat" in cmd
        assert "-q" in cmd and "hello world" in cmd
        assert "-Q" in cmd
        assert "--yolo" in cmd

    def test_respects_alias_as_command(self):
        from src.providers.hermes import HermesCLIExecutor
        from src.providers.base import RequestContext
        ex = HermesCLIExecutor()
        ctx = RequestContext(
            session_id="s1", exec_user="u", content="hi", provider="hermes", alias="hermes-custom"
        )
        cmd = ex._build_command(ctx)
        assert cmd[0] == "hermes-custom"

    def test_model_flag_from_inline_directive(self):
        from src.providers.hermes import HermesCLIExecutor
        from src.providers.base import RequestContext
        ex = HermesCLIExecutor()
        ctx = RequestContext(
            session_id="s1", exec_user="u", content="--model anthropic/claude hello", provider="hermes"
        )
        cmd = ex._build_command(ctx)
        assert "-m" in cmd
        idx = cmd.index("-m")
        assert cmd[idx + 1] == "anthropic/claude"
        assert "hello" in cmd


class TestOpenClawCommand:
    def test_builds_agent_json_command(self):
        from src.providers.openclaw import OpenClawCLIExecutor
        from src.providers.base import RequestContext
        ex = OpenClawCLIExecutor()
        ctx = RequestContext(
            session_id="s1", exec_user="u", content="do the thing", provider="openclaw"
        )
        cmd = ex._build_command(ctx)
        assert cmd[0] == "openclaw"
        assert "agent" in cmd
        assert "--message" in cmd and "do the thing" in cmd
        assert "--json" in cmd

    def test_does_not_pass_model_per_task(self):
        """OpenClaw binds the model at agent-registration time, not per task."""
        from src.providers.openclaw import OpenClawCLIExecutor
        from src.providers.base import RequestContext
        ex = OpenClawCLIExecutor()
        ctx = RequestContext(
            session_id="s1", exec_user="u", content="--model gpt-4 task", provider="openclaw"
        )
        cmd = ex._build_command(ctx)
        assert "--model" not in cmd

    def test_default_agent_option(self):
        from src.providers.openclaw import OpenClawExecutorConfig, OpenClawCLIExecutor
        from src.providers.base import RequestContext
        ex = OpenClawCLIExecutor(OpenClawExecutorConfig(default_agent="worker-1"))
        ctx = RequestContext(
            session_id="s1", exec_user="u", content="task", provider="openclaw"
        )
        cmd = ex._build_command(ctx)
        assert "--agent" in cmd
        assert cmd[cmd.index("--agent") + 1] == "worker-1"


# ---------------------------------------------------------------------------
# detection layer
# ---------------------------------------------------------------------------

def test_runtime_meta_includes_new_providers():
    from src.server.services.agent_runtimes import RUNTIME_META
    assert "hermes" in RUNTIME_META and "openclaw" in RUNTIME_META
    assert RUNTIME_META["hermes"].binaries == ["hermes"]
    assert RUNTIME_META["openclaw"].binaries == ["openclaw"]
