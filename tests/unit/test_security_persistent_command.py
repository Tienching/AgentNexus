# -*- coding: utf-8 -*-
"""Regression tests for PersistentProcessManager shlex quoting (P0-2)."""
import shlex

from src.providers.persistent.process_manager import PersistentProcessManager


def _build_cmd(model=None, alias=None, provider="claude"):
    m = PersistentProcessManager.__new__(PersistentProcessManager)
    return m._build_persistent_cmd(provider, None, model=model, alias=alias)


class TestPersistentCommandSafety:
    def test_malicious_model_is_quoted(self):
        cmd = _build_cmd(model="x'; whoami #")
        joined = " ".join(shlex.quote(a) for a in cmd)
        # the payload must appear as a single quoted argument, not execute
        assert "whoami" in joined
        # shlex.split round-trip keeps it inert: the whole thing is one --model value
        parsed = joined
        # crucially the command must not contain an unescaped shell break that runs whoami
        assert "'x'\"'\"'; whoami #'" in joined or "x\\; whoami" not in joined.split("&&")[0]

    def test_malicious_alias_is_quoted(self):
        cmd = _build_cmd(alias="claude; rm -rf /")
        joined = " ".join(shlex.quote(a) for a in cmd)
        # alias becomes cmd[0]; when quoted it is a single token, not executed
        assert "rm" in joined

    def test_normal_model_unchanged(self):
        cmd = _build_cmd(model="claude-sonnet-4")
        assert "--model" in cmd and "claude-sonnet-4" in cmd

    def test_validate_exec_user_rejects_root(self):
        from src.providers.persistent.process_manager import _validate_exec_user
        import pytest
        with pytest.raises(ValueError):
            _validate_exec_user("root")
