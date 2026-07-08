# -*- coding: utf-8 -*-
"""Nexus Authentication Router

Provides login/logout endpoints and authentication middleware for Nexus UI.
Authentication is optional - only enabled when NEXUS_PASSWORD is set.
"""

from __future__ import annotations

import os
import secrets
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from src.core.auth.rbac import AuthenticatedUser, Role, get_current_user, set_current_user
from ..config import Settings, settings
from ..logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/nexus/auth", tags=["nexus-auth"])

# SQLite-backed session store (fallback to in-memory if DB unavailable)
_session_key_prefix = "nexus:session:"
_memory_sessions: dict[str, float] = {}  # token -> expiry_timestamp

# Cap the fallback in-memory session map at this many entries to prevent
# unbounded memory growth under repeated failed-Redis / unauthenticated scenarios.
# Ported from mission-control rate-limit.ts maxEntries eviction (commit e7aa7e6).
_MEMORY_SESSIONS_MAX_ENTRIES: int = 10_000


def _evict_oldest_session() -> None:
    """Evict the session with the earliest (smallest) expiry timestamp.

    Called when the fallback store is at capacity before inserting a new entry.
    Mirrors MC's evictOldest() for rate-limiter maps: find the entry with the
    smallest resetAt (here: expiry timestamp) and delete it.
    """
    if not _memory_sessions:
        return
    oldest_token = min(_memory_sessions, key=lambda t: _memory_sessions[t])
    _memory_sessions.pop(oldest_token, None)


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    token: Optional[str] = None


class AuthStatusResponse(BaseModel):
    authenticated: bool
    auth_required: bool


def _connection_settings(connection: Request | None = None) -> Settings:
    """Return the settings bound to this FastAPI app, falling back to process settings."""
    app = getattr(connection, "app", None) if connection is not None else None
    if app is None and connection is not None:
        app = getattr(connection, "scope", {}).get("app")
    return getattr(getattr(app, "state", None), "settings", settings)


def _is_auth_required(app_settings: Settings | None = None) -> bool:
    """Check if authentication is required (NEXUS_PASSWORD is set)."""
    app_settings = app_settings or settings
    return bool(app_settings.nexus_password and app_settings.nexus_password.strip())


def _get_api_token(app_settings: Settings | None = None) -> str:
    # Prefer the Settings-managed value for the current FastAPI app. Fall back to
    # the raw environment for explicit `export NEXUS_AUTH_TOKEN=...` usage.
    app_settings = app_settings or settings
    val = getattr(app_settings, "nexus_auth_token", None) or os.getenv("NEXUS_AUTH_TOKEN")
    return (val or "").strip()


def _verify_password(password: str, app_settings: Settings | None = None) -> bool:
    """Verify the provided password against configured NEXUS_PASSWORD."""
    app_settings = app_settings or settings
    if not _is_auth_required(app_settings):
        return True
    # Use constant-time comparison to prevent timing attacks
    return secrets.compare_digest(
        password.encode("utf-8"),
        app_settings.nexus_password.encode("utf-8")
    )


def _generate_token() -> str:
    """Generate a secure session token"""
    return secrets.token_urlsafe(32)


def _session_key(token: str) -> str:
    return f"{_session_key_prefix}{token}"


def _session_db():
    """Get the SQLite database for session tokens."""
    try:
        from src.runtime.stores.db import get_db
        db = get_db()
        # Ensure table exists (idempotent)
        db.execute("CREATE TABLE IF NOT EXISTS auth_sessions (token TEXT PRIMARY KEY, expires_at REAL NOT NULL)")
        return db
    except Exception:
        return None


def _redis_available() -> bool:
    """Legacy compatibility helper for tests that previously patched Redis availability."""
    return _session_db() is not None


def _create_session(token: str, app_settings: Settings | None = None) -> None:
    """Create a new session with expiry (SQLite preferred, fallback to memory)."""
    app_settings = app_settings or settings
    ttl = int(app_settings.nexus_session_ttl)
    expiry = time.time() + ttl

    db = _session_db() if _redis_available() else None
    if db:
        try:
            with db.transaction() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO auth_sessions (token, expires_at) VALUES (?, ?)",
                    (token, expiry),
                )
            return
        except Exception as e:
            logger.warning(f"SQLite session set failed, fallback to memory: {e}")

    # Evict oldest before inserting when at capacity.
    if token not in _memory_sessions and len(_memory_sessions) >= _MEMORY_SESSIONS_MAX_ENTRIES:
        _evict_oldest_session()
    _memory_sessions[token] = expiry
    _cleanup_expired_sessions()


def _cleanup_expired_sessions() -> None:
    """Remove expired sessions from memory store."""
    now = time.time()
    expired = [t for t, exp in _memory_sessions.items() if exp < now]
    for t in expired:
        _memory_sessions.pop(t, None)


def _validate_session(token: str) -> bool:
    """Check if a session token is valid."""
    if not token:
        return False

    db = _session_db() if _redis_available() else None
    if db:
        try:
            row = db.execute_fetchone(
                "SELECT expires_at FROM auth_sessions WHERE token = ?", (token,)
            )
            if row:
                if time.time() > row["expires_at"]:
                    # Expired — clean up
                    with db.transaction() as conn:
                        conn.execute("DELETE FROM auth_sessions WHERE token = ?", (token,))
                    return False
                return True
            # Not in DB — check memory fallback
        except Exception as e:
            logger.warning(f"SQLite session check failed, fallback to memory: {e}")

    expiry = _memory_sessions.get(token)
    if not expiry:
        return False
    if time.time() > expiry:
        _memory_sessions.pop(token, None)
        return False
    return True


def _invalidate_session(token: str) -> None:
    """Invalidate a session token."""
    if not token:
        return

    db = _session_db() if _redis_available() else None
    if db:
        try:
            with db.transaction() as conn:
                conn.execute("DELETE FROM auth_sessions WHERE token = ?", (token,))
        except Exception as e:
            logger.warning(f"SQLite session delete failed: {e}")

    _memory_sessions.pop(token, None)


def get_auth_token(request: Request) -> Optional[str]:
    """Extract auth token from request (cookie or header)"""
    # Try cookie first
    token = request.cookies.get("nexus_token")
    if token:
        return token
    # Try Authorization header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None


def _build_authenticated_user(request: Request, *, allow_header_user: bool = False) -> AuthenticatedUser:
    # X-Nexus-User is a development/convenience header, not a verified identity.
    # Do not honor it for bearer-token or password-session authenticated requests,
    # otherwise any token holder can spoof audit actors.
    app_settings = _connection_settings(request)
    header_user = request.headers.get("X-Nexus-User") if allow_header_user else None
    username = (header_user or app_settings.exec_user or "nexus").strip() or "nexus"
    # Privilege is now tied to HOW the user was authenticated:
    #   - allow_header_user=True means "no real credential was checked" (the
    #     development / open-deployment fallback). Such callers get the least
    #     privilege (VIEWER) and never administrative scopes, so an unauthenticated
    #     deployment cannot mutate the control plane.
    #   - allow_header_user=False means a real token or password session matched,
    #     so the caller is trusted as ADMIN.
    if allow_header_user:
        logger.warning(
            "Granting VIEWER role to unauthenticated request (auth not configured); "
            "set NEXUS_PASSWORD or NEXUS_AUTH_TOKEN to enforce real authentication."
        )
        return AuthenticatedUser(username=username, role=Role.VIEWER, scopes=[])
    return AuthenticatedUser(username=username, role=Role.ADMIN, scopes=["admin"])


def get_authenticated_nexus_user(request: Request) -> AuthenticatedUser:
    user = getattr(request.state, "nexus_user", None) or get_current_user()
    if user is not None:
        return user
    app_settings = _connection_settings(request)
    if not _is_auth_required(app_settings) and not _get_api_token(app_settings):
        user = _build_authenticated_user(request, allow_header_user=True)
        request.state.nexus_user = user
        set_current_user(user)
        return user
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_nexus_admin(request: Request) -> AuthenticatedUser:
    user = get_authenticated_nexus_user(request)
    if user.has_role(Role.ADMIN):
        return user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")


async def verify_nexus_auth(request: Request) -> bool:
    """Dependency to verify Nexus authentication.
    
    Returns True if authenticated or auth not required.
    Raises HTTPException if auth required but not authenticated.
    """
    token = get_auth_token(request)
    set_current_user(None)

    app_settings = _connection_settings(request)
    api_token = _get_api_token(app_settings)
    if api_token:
        token_matches_api_key = bool(token and secrets.compare_digest(token, api_token))
        token_matches_password_session = bool(_is_auth_required(app_settings) and _validate_session(token))
        if token_matches_api_key or token_matches_password_session:
            user = _build_authenticated_user(request, allow_header_user=False)
            request.state.nexus_user = user
            set_current_user(user)
            return True
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not _is_auth_required(app_settings):
        user = _build_authenticated_user(request, allow_header_user=True)
        request.state.nexus_user = user
        set_current_user(user)
        return True

    if _validate_session(token):
        user = _build_authenticated_user(request, allow_header_user=False)
        request.state.nexus_user = user
        set_current_user(user)
        return True

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status(request: Request):
    """Check authentication status.
    
    Returns whether auth is required and current authentication state.
    """
    app_settings = _connection_settings(request)
    auth_required = _is_auth_required(app_settings) or bool(_get_api_token(app_settings))
    
    if not auth_required:
        return AuthStatusResponse(authenticated=True, auth_required=False)
    
    token = get_auth_token(request)
    api_token = _get_api_token(app_settings)
    if api_token:
        authenticated = bool(
            token
            and (
                secrets.compare_digest(token, api_token)
                or (_is_auth_required(app_settings) and _validate_session(token))
            )
        )
    else:
        authenticated = _validate_session(token)
    
    return AuthStatusResponse(authenticated=authenticated, auth_required=True)


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, response: Response, http_request: Request):
    """Login to Nexus UI.

    If NEXUS_PASSWORD is not set, always succeeds.
    """
    app_settings = _connection_settings(http_request)
    api_token = _get_api_token(app_settings)
    password_required = _is_auth_required(app_settings)

    if not password_required:
        if not api_token:
            return LoginResponse(success=True, message="Authentication not required")
        if not secrets.compare_digest((request.password or "").encode("utf-8"), api_token.encode("utf-8")):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid password",
            )
        token = api_token
    else:
        if not _verify_password(request.password, app_settings):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid password",
            )
        # Generate and store session token for password-based UI logins.
        token = _generate_token()
        _create_session(token, app_settings)

    # Set cookie — only mark Secure when behind HTTPS to avoid
    # silent cookie rejection on plain-HTTP deployments.
    _is_https = http_request.url.scheme == "https"
    response.set_cookie(
        key="nexus_token",
        value=token,
        max_age=app_settings.nexus_session_ttl,
        httponly=True,
        samesite="lax",
        secure=_is_https,
    )
    
    logger.info("Nexus login successful")
    return LoginResponse(success=True, message="Login successful", token=token)


@router.post("/logout")
async def logout(request: Request, response: Response):
    """Logout from Nexus UI."""
    token = get_auth_token(request)
    if token:
        _invalidate_session(token)
    
    response.delete_cookie("nexus_token")
    return {"success": True, "message": "Logged out"}
