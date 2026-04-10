# -*- coding: utf-8 -*-
"""RBAC (Role-Based Access Control) system for API authentication.

Implements three-tier role hierarchy:
    - viewer (level 0): Read-only access
    - operator (level 1): Read-write access, can execute tasks
    - admin (level 2): Full access including system management

Usage:
    from src.core.auth.rbac import require_role, check_permission, Role

    # In a FastAPI route
    @app.get("/agents")
    async def list_agents(request: Request):
        auth = require_role(request, Role.VIEWER)
        if auth.error:
            return JSONResponse({"error": auth.error}, status_code=auth.status)
        # auth.user contains the authenticated user info
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Role hierarchy
# ---------------------------------------------------------------------------

class Role(str, Enum):
    """User roles in the RBAC system.

    Hierarchy (ascending privilege):
        viewer < operator < admin
    """
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"


# Numeric levels for comparison
ROLE_LEVELS: dict[Role, int] = {
    Role.VIEWER: 0,
    Role.OPERATOR: 1,
    Role.ADMIN: 2,
}


def role_from_string(value: str) -> Role:
    """Convert a string to a Role enum value.

    Args:
        value: Role string ('viewer', 'operator', 'admin')

    Returns:
        The corresponding Role enum value

    Raises:
        ValueError: If the string is not a valid role
    """
    try:
        return Role(value.lower())
    except ValueError:
        valid = ", ".join(r.value for r in Role)
        raise ValueError(f"Unknown role '{value}'. Valid roles: {valid}") from None


def get_role_level(role: Role) -> int:
    """Get the numeric privilege level for a role."""
    return ROLE_LEVELS.get(role, -1)


# ---------------------------------------------------------------------------
# User model
# ---------------------------------------------------------------------------

@dataclass
class AuthenticatedUser:
    """Represents an authenticated user with their role."""
    username: str
    role: Role
    scopes: list[str] = None  # Optional API key scopes

    def __post_init__(self):
        if self.scopes is None:
            self.scopes = []

    def has_role(self, min_role: Role) -> bool:
        """Check if user has at least the minimum required role."""
        return ROLE_LEVELS.get(self.role, -1) >= ROLE_LEVELS.get(min_role, -1)

    def has_scope(self, scope: str) -> bool:
        """Check if user has a specific scope."""
        return scope in self.scopes or "admin" in self.scopes


# ---------------------------------------------------------------------------
# Auth result union (success or failure)
# ---------------------------------------------------------------------------

@dataclass
class AuthSuccess:
    """Authentication succeeded."""
    user: AuthenticatedUser


@dataclass
class AuthFailure:
    """Authentication or authorization failed."""
    error: str
    status: int  # 401 for auth failure, 403 for permission denied


# Union type for auth result
AuthResult = AuthSuccess | AuthFailure


# ---------------------------------------------------------------------------
# Current user context (thread-local for sync, context vars for async)
# ---------------------------------------------------------------------------

import contextvars

_current_user: contextvars.ContextVar[Optional[AuthenticatedUser]] = contextvars.ContextVar(
    "current_user", default=None
)


def set_current_user(user: Optional[AuthenticatedUser]) -> None:
    """Set the current authenticated user for this context."""
    _current_user.set(user)


def get_current_user() -> Optional[AuthenticatedUser]:
    """Get the current authenticated user, if any."""
    return _current_user.get()


# ---------------------------------------------------------------------------
# require_role - the main RBAC enforcement function
# ---------------------------------------------------------------------------

def require_role(
    username: str,
    role: Role,
) -> AuthResult:
    """Check if the current user has at least the minimum required role.

    This is the primary function for RBAC enforcement in route handlers.

    Usage:
        auth = require_role(request, Role.VIEWER)
        if auth.error:
            return JSONResponse({"error": auth.error}, status_code=auth.status)
        # auth.user contains the authenticated user

    Args:
        username: The username to check
        role: Minimum required role

    Returns:
        AuthSuccess(user) if authorized, AuthFailure(error, status) if not
    """
    user = get_current_user()

    if user is None:
        return AuthFailure(error="Authentication required", status=401)

    if not user.has_role(role):
        logger.warning(
            "Access denied: user %s has role %s but requires %s",
            user.username, user.role.value, role.value
        )
        return AuthFailure(
            error=f"Requires {role.value} role or higher",
            status=403
        )

    return AuthSuccess(user=user)


def check_permission(
    username: str,
    required_role: Role,
) -> bool:
    """Simple boolean permission check.

    Use this when you just want a True/False answer without the
    detailed AuthResult.

    Args:
        username: Username to check
        required_role: Minimum required role

    Returns:
        True if authorized, False otherwise
    """
    auth = require_role(username, required_role)
    return not isinstance(auth, AuthFailure)


# ---------------------------------------------------------------------------
# Role requirement decorator for FastAPI routes
# ---------------------------------------------------------------------------

from functools import wraps
from typing import Callable, TypeVar, ParamSpec
import asyncio

P = ParamSpec('P')
T = TypeVar('T')


def require_role_decorator(min_role: Role) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorator that enforces a minimum role requirement on a route handler.

    Usage:
        @app.get("/agents")
        @require_role_decorator(Role.VIEWER)
        async def list_agents():
            user = get_current_user()
            return {"agents": [...]}

    Note: This decorator must be applied AFTER the FastAPI route decorator
    since FastAPI decorators don't preserve function metadata properly.
    Consider using dependency injection instead:

        async def get_current_user(request: Request) -> AuthenticatedUser:
            auth = require_role(request, Role.VIEWER)
            if auth.error:
                raise HTTPException(status_code=auth.status, detail=auth.error)
            return auth.user

        @app.get("/agents")
        async def list_agents(user: AuthenticatedUser = Depends(get_current_user)):
            return {"agents": [...]}
    """
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            user = get_current_user()
            if user is None:
                raise PermissionError("Authentication required")
            if not user.has_role(min_role):
                raise PermissionError(f"Requires {min_role.value} role or higher")
            return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            user = get_current_user()
            if user is None:
                raise PermissionError("Authentication required")
            if not user.has_role(min_role):
                raise PermissionError(f"Requires {min_role.value} role or higher")
            return func(*args, **kwargs)

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# ---------------------------------------------------------------------------
# Built-in role permission sets
# ---------------------------------------------------------------------------

# Permissions that each role is allowed to perform
ROLE_PERMISSIONS: dict[Role, set[str]] = {
    Role.VIEWER: {
        "read:agents", "read:tasks", "read:sessions", "read:schedules",
        "read:config", "read:history", "read:features",
    },
    Role.OPERATOR: {
        "read:agents", "read:tasks", "read:sessions", "read:schedules",
        "read:config", "read:history", "read:features",
        "write:tasks", "write:sessions", "write:schedules",
        "exec:agents", "exec:tasks", "exec:schedules",
    },
    Role.ADMIN: {
        # All permissions
        "read:agents", "read:tasks", "read:sessions", "read:schedules",
        "read:config", "read:history", "read:features",
        "write:tasks", "write:sessions", "write:schedules",
        "write:agents", "write:config", "write:features",
        "exec:agents", "exec:tasks", "exec:schedules",
        "admin:system", "admin:webhooks", "admin:security",
    },
}


def has_permission(user: AuthenticatedUser, permission: str) -> bool:
    """Check if a user has a specific permission.

    Args:
        user: The authenticated user
        permission: Permission string (e.g., "read:tasks", "admin:system")

    Returns:
        True if the user has the permission, False otherwise
    """
    # Admin has all permissions
    if user.role == Role.ADMIN:
        return True

    # Check if user's role includes the permission
    return permission in ROLE_PERMISSIONS.get(user.role, set())
