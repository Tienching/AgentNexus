# -*- coding: utf-8 -*-
"""Regression tests for SSRF protection helpers."""
import pytest

from src.core.agent_runtime.security.network import validate_url_target, validate_resolved_url


class TestSSRFGuard:
    @pytest.mark.parametrize("url", [
        "http://127.0.0.1/",
        "http://localhost/",
        "http://10.0.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",   # cloud metadata
        "http://172.16.0.1/",
        "http://[::ffff:127.0.0.1]/",
        "http://[::ffff:169.254.169.254]/latest/meta-data/",
        "ftp://example.com/",                          # bad scheme
    ])
    def test_internal_or_bad_scheme_rejected(self, url):
        ok, err = validate_url_target(url)
        assert not ok, f"{url} should be blocked"

    def test_public_domain_accepted(self):
        # example.com resolves to a public address
        ok, err = validate_url_target("https://example.com/")
        assert ok, f"expected ok, got: {err}"

    def test_validate_resolved_url_blocks_private(self):
        ok, _ = validate_resolved_url("http://10.1.2.3/")
        assert not ok

    def test_validate_resolved_url_blocks_ipv4_mapped_ipv6(self):
        ok, _ = validate_resolved_url("http://[::ffff:127.0.0.1]/")
        assert not ok


class TestSSRFIntegration:
    def test_callback_handler_imports_guard(self):
        import inspect
        from src.server.services import callback_handler
        src = inspect.getsource(callback_handler)
        assert "validate_url_target" in src

    def test_media_downloader_imports_guard(self):
        import inspect
        from src.server.services import media_downloader
        src = inspect.getsource(media_downloader)
        assert "validate_url_target" in src

    def test_teleport_bridge_imports_guard(self):
        import inspect
        from src.server.services import teleport_bridge
        src = inspect.getsource(teleport_bridge)
        assert "validate_url_target" in src

def test_media_downloader_validates_redirect_target():
    import inspect
    from src.server.services import media_downloader

    src = inspect.getsource(media_downloader)
    assert "validate_url_target" in src
    assert "validate_resolved_url" in src
    assert "follow_redirects=False" in src
    assert "Blocked unsafe redirected image URL" in src
    assert "Blocked unsafe redirected file URL" in src


def test_web_fetch_does_not_auto_follow_redirects_before_validation():
    import inspect
    from src.core.agent_runtime.agent.tools import web

    module_src = inspect.getsource(web)
    class_src = inspect.getsource(web.WebFetchTool)
    assert "follow_redirects=False" in class_src
    assert "validate_redirect_location" in module_src


def test_rate_limiter_ignores_x_forwarded_for_by_default(monkeypatch):
    from src.server.middleware.rate_limit import RateLimitMiddleware

    monkeypatch.delenv("TRUST_PROXY_HEADERS", raising=False)
    middleware = RateLimitMiddleware(lambda scope, receive, send: None)

    class Client:
        host = "1.2.3.4"

    class Request:
        headers = {"x-forwarded-for": "9.9.9.9"}
        client = Client()

    assert middleware._client_key(Request()) == "1.2.3.4"


@pytest.mark.asyncio
async def test_rate_limiter_normalizes_colon_port_path_prefix(monkeypatch):
    from src.server.middleware.rate_limit import RateLimitMiddleware

    monkeypatch.setenv("RATE_LIMIT_CHAT_CAPACITY", "0")
    monkeypatch.setenv("RATE_LIMIT_CHAT_REFILL", "0")
    middleware = RateLimitMiddleware(lambda scope, receive, send: None)

    class URL:
        path = "/:8081/chat/stream/ubuntu"

    class Client:
        host = "1.2.3.4"

    class Request:
        url = URL()
        headers = {}
        client = Client()

    async def call_next(_request):
        raise AssertionError("prefixed chat stream path should be rate limited")

    response = await middleware.dispatch(Request(), call_next)
    assert response.status_code == 429
    assert response.headers["X-RateLimit-Path"] == "/chat/stream"


# ---------------------------------------------------------------------------
# _normalize_path direct coverage (P1 fix)
# ---------------------------------------------------------------------------
class TestNormalizePath:
    def _n(self, p):
        from src.server.middleware.rate_limit import _normalize_path
        return _normalize_path(p)

    def test_strips_port_prefix_before_chat_stream(self):
        assert self._n("/:8081/chat/stream/ubuntu") == "/chat/stream/ubuntu"

    def test_strips_port_prefix_before_login(self):
        assert self._n("/:8081/api/nexus/auth/login") == "/api/nexus/auth/login"

    def test_passes_through_unprefixed_protected_paths(self):
        assert self._n("/chat/stream/ubuntu") == "/chat/stream/ubuntu"
        assert self._n("/api/nexus/auth/login") == "/api/nexus/auth/login"

    def test_keeps_non_digit_port_segment(self):
        # /:abc/... is not a valid legacy port prefix; left untouched
        assert self._n("/:abc/chat/stream/x") == "/:abc/chat/stream/x"

    def test_keeps_port_prefix_before_unprotected_path(self):
        # /:8081/other must NOT be rewritten (would mask a real route)
        assert self._n("/:8081/other/path") == "/:8081/other/path"

    def test_keeps_root_and_plain_paths(self):
        assert self._n("/") == "/"
        assert self._n("/health") == "/health"

    def test_empty_string_returned_unchanged(self):
        assert self._n("") == ""

    def test_bare_port_prefix_with_nothing_after_unchanged(self):
        # /:8081 with no following protected prefix → left untouched
        assert self._n("/:8081") == "/:8081"

    def test_leading_zero_port_stripped(self):
        # /:0001/chat/stream/x → router accepts [1:].isdigit() too
        assert self._n("/:0001/chat/stream/x") == "/chat/stream/x"


# ---------------------------------------------------------------------------
# defaultdict removal (P3): buckets behave as a plain dict
# ---------------------------------------------------------------------------
class TestBucketsArePlainDict:
    def test_missing_key_returns_none_not_bucket(self):
        from src.server.middleware.rate_limit import RateLimitMiddleware
        m = RateLimitMiddleware(lambda scope, receive, send: None)
        # plain dict: a missing key is just None, no auto-created sentinel
        assert m._buckets.get(("nonexistent", "1.2.3.4")) is None
        assert m._buckets == {}


# ---------------------------------------------------------------------------
# multi-worker warning (P2)
# ---------------------------------------------------------------------------
class TestMultiWorkerWarning:
    def test_warns_when_api_workers_gt_1(self, monkeypatch, caplog):
        import logging
        from src.server.config import settings
        from src.server.middleware.rate_limit import RateLimitMiddleware

        monkeypatch.setattr(settings, "api_workers", 4, raising=False)
        with caplog.at_level(logging.WARNING, logger="src.server.middleware.rate_limit"):
            RateLimitMiddleware(lambda scope, receive, send: None)
        assert any("api_workers=4" in r.message for r in caplog.records)

    def test_no_warning_when_single_worker(self, monkeypatch, caplog):
        import logging
        from src.server.config import settings
        from src.server.middleware.rate_limit import RateLimitMiddleware

        monkeypatch.setattr(settings, "api_workers", 1, raising=False)
        with caplog.at_level(logging.WARNING, logger="src.server.middleware.rate_limit"):
            RateLimitMiddleware(lambda scope, receive, send: None)
        assert not any("api_workers=" in r.message for r in caplog.records)
