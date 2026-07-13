from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from src.server.routers import nexus_files
from src.server.services.user_directory import UserDirectoryManager


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "kwargs"),
    [
        (nexus_files.list_session_files, {"subpath": ""}),
        (nexus_files.download_session_file, {"file_path": "result.txt"}),
    ],
)
async def test_file_routes_reject_invalid_exec_user_before_path_resolution(
    monkeypatch, handler, kwargs
):
    reject = AsyncMock(side_effect=HTTPException(status_code=400, detail="invalid exec_user"))
    resolve_folder = Mock()
    monkeypatch.setattr(nexus_files, "validate_exec_user", reject)
    monkeypatch.setattr(nexus_files, "_resolve_session_folder", resolve_folder)

    with pytest.raises(HTTPException) as exc_info:
        await handler("session-1", exec_user="/tmp", **kwargs)

    assert exc_info.value.status_code == 400
    reject.assert_awaited_once_with("/tmp")
    resolve_folder.assert_not_called()


@pytest.mark.parametrize("exec_user", ["/tmp", "../ubuntu", "a/b", "", "user name"])
def test_user_directory_rejects_non_username_path_components(exec_user):
    config = Mock(user_home_base="/home")

    with pytest.raises(ValueError, match="invalid exec_user"):
        UserDirectoryManager(config).resolve_user_home(exec_user)
