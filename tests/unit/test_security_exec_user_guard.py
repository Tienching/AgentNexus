# -*- coding: utf-8 -*-
"""Regression tests for exec_user validation (P0-1)."""
import pytest
from fastapi import HTTPException

from src.server.security.exec_user_guard import validate_exec_user


class TestExecUserGuard:
    async def test_valid_existing_user_accepted(self):
        # ubuntu always exists on the dev box
        assert await validate_exec_user("ubuntu") == "ubuntu"

    @pytest.mark.parametrize("bad", [
        "", "  ", "root", "nobody", "daemon",           # reserved / empty
        "a;b", "user name", "a$b", "user\x00",          # shell metacharacters
        "../../../etc", "-c", "--help",                 # path traversal / flags
        "a" * 33,                                       # too long
        "1abc",                                         # starts with digit
    ])
    async def test_invalid_or_reserved_rejected(self, bad):
        with pytest.raises(HTTPException) as exc:
            await validate_exec_user(bad)
        assert exc.value.status_code in (400, 403)

    async def test_nonexistent_user_rejected(self):
        with pytest.raises(HTTPException) as exc:
            await validate_exec_user("definitely_not_a_real_user_xyz123")
        assert exc.value.status_code == 400
        # must NOT echo the username (user-enumeration prevention)
        assert "definitely_not_a_real_user_xyz123" not in exc.value.detail

    async def test_whitelist_enforced(self, monkeypatch):
        # ubuntu is real; whitelist restricts to a different user
        monkeypatch.setenv("ALLOWED_EXEC_USERS", "someoneelse")
        with pytest.raises(HTTPException) as exc:
            await validate_exec_user("ubuntu")
        assert exc.value.status_code == 403

    async def test_whitelist_allows_member(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_EXEC_USERS", "ubuntu")
        assert await validate_exec_user("ubuntu") == "ubuntu"

def test_session_storage_rejects_reserved_exec_user():
    from src.runtime.stores.session_storage import SessionStorage

    storage = SessionStorage(redis_client=object())
    assert storage.set_session_exec_user("s1", "root") is False
