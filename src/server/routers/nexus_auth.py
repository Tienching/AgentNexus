# -*- coding: utf-8 -*-
"""Nexus Authentication Router

Provides login/logout endpoints and authentication middleware for Nexus UI.
Authentication is optional - only enabled when NEXUS_PASSWORD is set.
"""

from __future__ import annotations

import secrets
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from ..config import settings
from ..logger import get_logger
from ..services.redis_client import get_redis_client

logger = get_logger(__name__)

router = APIRouter(prefix="/api/nexus/auth", tags=["nexus-auth"])

# Redis-backed session store (fallback to in-memory if Redis is unavailable)
_redis = get_redis_client()
_session_key_prefix = "nexus:session:"
_memory_sessions: dict[str, float] = {}  # token -> expiry_timestamp


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    token: Optional[str] = None


class AuthStatusResponse(BaseModel):
    authenticated: bool
    auth_required: bool


def _is_auth_required() -> bool:
    """Check if authentication is required (NEXUS_PASSWORD is set)"""
    return bool(settings.nexus_password and settings.nexus_password.strip())


def _verify_password(password: str) -> bool:
    """Verify the provided password against configured NEXUS_PASSWORD"""
    if not _is_auth_required():
        return True
    # Use constant-time comparison to prevent timing attacks
    return secrets.compare_digest(
        password.encode("utf-8"),
        settings.nexus_password.encode("utf-8")
    )


def _generate_token() -> str:
    """Generate a secure session token"""
    return secrets.token_urlsafe(32)


def _session_key(token: str) -> str:
    return f"{_session_key_prefix}{token}"


def _redis_available() -> bool:
    try:
        return _redis.ping()
    except Exception:
        return False


def _create_session(token: str) -> None:
    """Create a new session with expiry (Redis preferred, fallback to memory)."""
    ttl = int(settings.nexus_session_ttl)
    if _redis_available():
        try:
            _redis.set(_session_key(token), "1", ex=ttl)
            return
        except Exception as e:
            logger.warning(f"Redis session set failed, fallback to memory: {e}")

    expiry = time.time() + ttl
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

    if _redis_available():
        try:
            return _redis.exists(_session_key(token))
        except Exception as e:
            logger.warning(f"Redis session check failed, fallback to memory: {e}")

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

    if _redis_available():
        try:
            _redis.delete(_session_key(token))
        except Exception as e:
            logger.warning(f"Redis session delete failed: {e}")

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


async def verify_nexus_auth(request: Request) -> bool:
    """Dependency to verify Nexus authentication.
    
    Returns True if authenticated or auth not required.
    Raises HTTPException if auth required but not authenticated.
    """
    if not _is_auth_required():
        return True
    
    token = get_auth_token(request)
    if _validate_session(token):
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
    auth_required = _is_auth_required()
    
    if not auth_required:
        return AuthStatusResponse(authenticated=True, auth_required=False)
    
    token = get_auth_token(request)
    authenticated = _validate_session(token)
    
    return AuthStatusResponse(authenticated=authenticated, auth_required=True)


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, response: Response):
    """Login to Nexus UI.
    
    If NEXUS_PASSWORD is not set, always succeeds.
    """
    if not _is_auth_required():
        return LoginResponse(success=True, message="Authentication not required")
    
    if not _verify_password(request.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid password",
        )
    
    # Generate and store session token
    token = _generate_token()
    _create_session(token)
    
    # Set cookie
    response.set_cookie(
        key="nexus_token",
        value=token,
        max_age=settings.nexus_session_ttl,
        httponly=True,
        samesite="lax",
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
