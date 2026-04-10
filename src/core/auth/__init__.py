# -*- coding: utf-8 -*-
"""Authentication and RBAC module."""

from .rbac import (
    Role,
    role_from_string,
    get_role_level,
    AuthenticatedUser,
    AuthSuccess,
    AuthFailure,
    AuthResult,
    require_role,
    check_permission,
    has_permission,
    require_role_decorator,
    set_current_user,
    get_current_user,
    ROLE_PERMISSIONS,
)

__all__ = [
    "Role",
    "role_from_string",
    "get_role_level",
    "AuthenticatedUser",
    "AuthSuccess",
    "AuthFailure",
    "AuthResult",
    "require_role",
    "check_permission",
    "has_permission",
    "require_role_decorator",
    "set_current_user",
    "get_current_user",
    "ROLE_PERMISSIONS",
]
