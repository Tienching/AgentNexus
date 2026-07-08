# -*- coding: utf-8 -*-
"""Security response headers middleware.

Injects a baseline set of defensive HTTP response headers on every response to
harden against clickjacking, MIME-sniffing, protocol downgrade and referrer
leakage.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware


# Static security headers. HSTS is only meaningful over HTTPS and is therefore
# applied conditionally (see dispatch).
_BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "X-XSS-Protection": "1; mode=block",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    # Default-src 'self' keeps the NexusHub UI from loading unexpected assets;
    # explicit CDN allowances match the current index.html dependencies.
    #
    # Known limitation: 'unsafe-inline' is still required on script-src/style-src
    # because the UI ships inline <script>/<style> blocks (Tailwind play CDN +
    # per-page inline JS). This materially weakens XSS protection — a next step
    # is a nonce-based CSP (middleware mints a per-response nonce, templates
    # reference 'nonce-<rand>', and the unsafe-inline tokens are dropped).
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' https://cdn.tailwindcss.com https://cdn.jsdelivr.net 'unsafe-inline'; "
        "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
        "font-src 'self' https://cdn.jsdelivr.net data:; "
        "connect-src 'self' ws: wss:; "
        "img-src 'self' data: blob:; "
        "base-uri 'self'; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        "object-src 'none'"
    ),
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security response headers to every response."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        for key, value in _BASE_HEADERS.items():
            # Do not overwrite headers explicitly set by downstream handlers.
            response.headers.setdefault(key, value)
        # HSTS only over HTTPS (sending it over HTTP can be ignored/blocked
        # by browsers and is misleading).
        if request.url.scheme == "https":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response
