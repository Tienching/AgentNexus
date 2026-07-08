# -*- coding: utf-8 -*-
"""Rate-limiting middleware (token bucket, zero extra dependencies).

Protects brute-force / DoS prone endpoints (login, chat stream) with a simple
in-memory token bucket keyed by client IP. Buckets are pruned periodically to
bound memory.

This is intentionally lightweight; for a multi-process deployment swap in Redis
or slowapi. Defaults are conservative and can be tuned via env.

Multi-worker caveat
-------------------
The bucket state lives in-process. Under ``api_workers > 1`` each worker keeps
its own buckets, so the effective limit is ``configured_limit * workers``. The
constructor warns once when it detects a multi-worker deployment; for an exact
limit across workers, deploy the Redis backend (TODO) or pin ``api_workers = 1``
behind a process-level balancer.
"""

from __future__ import annotations

import logging
import os
import time
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Path prefixes that the chat router exposes for legacy frontends that glue the
# port (e.g. ``:8081``) onto the URL path, e.g. ``/:8081/chat/stream/<user>``.
# See routers/chat.py ``chat_stream_with_port_prefix``. Such prefixes must be
# stripped before matching a rate-limit rule so the limiter still applies.
_PORT_PATH_PREFIXES = ("/chat/stream", "/api/nexus/auth/login")


def _env_int(name, default):
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name, default):
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# (path_prefix, capacity, refill_per_second)
# capacity = burst size; refill = sustained rate.
def _rules():
    return [
        ("/api/nexus/auth/login", _env_int("RATE_LIMIT_LOGIN_CAPACITY", 5), _env_float("RATE_LIMIT_LOGIN_REFILL", 0.1)),
        ("/chat/stream", _env_int("RATE_LIMIT_CHAT_CAPACITY", 20), _env_float("RATE_LIMIT_CHAT_REFILL", 0.5)),
    ]


class _Bucket:
    __slots__ = ("tokens", "last")

    def __init__(self, capacity, now):
        self.tokens = float(capacity)
        self.last = now


def _normalize_path(path: str) -> str:
    """Strip a legacy ``/:<port>`` first segment so it matches limiter rules.

    The chat router accepts ``/:<port>/chat/stream/<user>`` for old frontends
    that mistakenly put the port in the path (see chat_stream_with_port_prefix).
    Without normalisation those requests would skip the limiter entirely. Only a
    leading ``/:<digits>`` segment that precedes a known protected prefix is
    removed; everything else is returned unchanged so we never mask real routes.
    """
    if not path.startswith("/:") or len(path) < 2:
        return path
    # first path segment after the leading "/:" up to the next "/"
    rest = path[2:]
    slash = rest.find("/")
    seg = rest if slash == -1 else rest[:slash]
    if not seg.isdigit():
        return path
    normalized = "" if slash == -1 else rest[slash:]
    # Only strip when what follows is a prefix we actually rate-limit, to avoid
    # silently rewriting unrelated ``/:<digits>/...`` paths.
    if normalized.startswith(_PORT_PATH_PREFIXES):
        return normalized
    return path


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token-bucket rate limiter keyed by client IP + path prefix."""

    # Prune idle buckets once this many seconds have passed.
    _PRUNE_INTERVAL = 300.0
    _BUCKET_TTL = 600.0

    def __init__(self, app, enabled: bool = True):
        super().__init__(app)
        self.enabled = enabled
        self._rules = _rules()
        # Plain dict: dispatch() always uses .get()/explicit assignment, so a
        # defaultdict (and its lambda: None default) only created confusion.
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        self._lock = Lock()
        self._last_prune = time.monotonic()
        if enabled:
            self._warn_if_multi_worker()

    def _warn_if_multi_worker(self) -> None:
        """Warn once if the process is one of several API workers.

        Effective rate limit scales with worker count because buckets are
        per-process. We cannot always detect the worker count from inside the
        middleware (uvicorn forks before importing the app), so we also accept
        an explicit ``API_WORKERS`` hint from the environment / settings.
        """
        try:
            from ..config import settings  # module-level singleton (Settings())
            workers = getattr(settings, "api_workers", 1)
        except Exception:
            workers = _env_int("API_WORKERS", 1)
        if workers and workers > 1:
            logger.warning(
                "RateLimitMiddleware running with api_workers=%s; effective rate "
                "limit is %sx the configured value (buckets are per-process). "
                "Use a shared Redis backend or api_workers=1 for an exact limit.",
                workers, workers,
            )

    def _client_key(self, request) -> str:
        # Only trust proxy-provided client IPs when deployment explicitly opts in.
        if os.getenv("TRUST_PROXY_HEADERS", "0").lower() in {"1", "true", "yes"}:
            fwd = request.headers.get("x-forwarded-for")
            if fwd:
                return fwd.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "unknown"

    async def dispatch(self, request, call_next):
        if not self.enabled:
            return await call_next(request)

        path = _normalize_path(request.url.path)
        matched = None
        for prefix, cap, refill in self._rules:
            if path.startswith(prefix):
                matched = (prefix, cap, refill)
                break
        if matched is None:
            return await call_next(request)

        prefix, capacity, refill = matched
        ip = self._client_key(request)
        key = (prefix, ip)
        now = time.monotonic()

        allowed = True
        retry_after = 0.0
        with self._lock:
            # Prune periodically.
            if now - self._last_prune > self._PRUNE_INTERVAL:
                stale = [k for k, b in self._buckets.items() if now - b.last > self._BUCKET_TTL]
                for k in stale:
                    self._buckets.pop(k, None)
                self._last_prune = now

            b = self._buckets.get(key)
            if b is None:
                b = _Bucket(capacity, now)
                self._buckets[key] = b
            else:
                elapsed = now - b.last
                b.tokens = min(float(capacity), b.tokens + elapsed * refill)
                b.last = now

            if b.tokens >= 1.0:
                b.tokens -= 1.0
            else:
                allowed = False
                retry_after = max(1.0, (1.0 - b.tokens) / refill) if refill > 0 else 1.0

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests"},
                headers={
                    "Retry-After": str(int(retry_after) + 1),
                    "X-RateLimit-Path": prefix,
                },
            )
        return await call_next(request)
