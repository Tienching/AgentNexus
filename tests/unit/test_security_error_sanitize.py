# -*- coding: utf-8 -*-
"""Regression tests for error-message sanitisation."""
import pytest

from src.providers._error_sanitize import safe_error_message as prov_safe
from src.server.utils.error_sanitize import safe_error_message as srv_safe


class TestErrorSanitize:
    def test_provider_hides_internal_details(self):
        msg = prov_safe(RuntimeError("secret /home/user/config.json detail"))
        assert "/home/user/config.json" not in msg
        assert "secret" not in msg

    def test_server_hides_internal_details(self):
        msg = srv_safe(ValueError("internal host=any1 path=/etc/passwd"))
        assert "any1" not in msg
        assert "/etc/passwd" not in msg

    def test_provider_returns_generic(self):
        assert "处理" in prov_safe(RuntimeError("x"))

    def test_provider_timeout_message(self):
        msg = prov_safe(TimeoutError("slow"), timeout=True)
        assert "超时" in msg

    def test_string_input_handled(self):
        assert "处理" in prov_safe("some raw error string")

    @pytest.mark.parametrize("fn", [prov_safe, srv_safe])
    def test_debug_mode_can_reveal(self, monkeypatch, fn):
        monkeypatch.setenv("NEXUS_DEBUG_ERRORS", "true")
        msg = fn(RuntimeError("hidden detail xyz"))
        assert "hidden detail xyz" in msg
