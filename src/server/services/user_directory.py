# -*- coding: utf-8 -*-
"""User Directory Management Service"""

import asyncio
import shlex
import os
import pwd
from pathlib import Path
from typing import Optional, Tuple

from ..config import settings
from ..logger import get_logger

logger = get_logger(__name__)


class UserDirectoryManager:
    """用户目录管理器"""

    def __init__(self, config=None):
        self.config = config or settings

    def resolve_user_home(self, exec_user: str) -> Path:
        """Resolve the effective home root for the given exec_user."""
        preferred_home = Path(self.config.user_home_base) / exec_user
        current_user = pwd.getpwuid(os.getuid()).pw_name
        if current_user != exec_user and os.geteuid() != 0:
            return Path.home() / exec_user
        return preferred_home

    def resolve_sessions_root(self, exec_user: str) -> Path:
        """Resolve the sessions root for the given exec_user."""
        return self.resolve_user_home(exec_user) / ".nexus" / "sessions"

    def resolve_session_directory(self, exec_user: str, session_id: str = "default") -> Path:
        """Resolve a session directory using the same rule as directory creation."""
        return self.resolve_sessions_root(exec_user) / session_id

    def resolve_task_session_directory(
        self,
        exec_user: str,
        task_id: str,
        session_id: Optional[str] = None,
    ) -> Tuple[Path, str, bool]:
        """Resolve the best-matching session directory for a task.

        Resolution order:
        1. Real `task.session_id` when its directory exists
        2. Legacy `*_{task_id}` suffix match
        3. Legacy `task_{task_id}` when it exists
        4. If nothing exists, return the preferred real session path (or legacy path when no real session_id is known)

        Returns:
            (resolved_dir, resolved_session_id, used_legacy_fallback)
        """
        normalized_task_id = (task_id or "").strip()
        normalized_session_id = (session_id or "").strip() or None
        sessions_dir = self.resolve_sessions_root(exec_user)

        preferred_session_id = normalized_session_id or f"task_{normalized_task_id}"
        preferred_dir = sessions_dir / preferred_session_id
        if normalized_session_id and preferred_dir.exists():
            return preferred_dir, preferred_session_id, False

        if normalized_task_id and sessions_dir.exists():
            suffix = f"_{normalized_task_id}"
            try:
                for child in sessions_dir.iterdir():
                    if child.is_dir() and child.name.endswith(suffix):
                        logger.info(
                            "Resolved task session directory via suffix fallback",
                            extra={
                                "exec_user": exec_user,
                                "task_id": normalized_task_id,
                                "resolved_session_id": child.name,
                            },
                        )
                        return child, child.name, True
            except OSError as e:
                logger.warning(
                    "Failed to scan sessions directory for legacy task session",
                    extra={
                        "exec_user": exec_user,
                        "task_id": normalized_task_id,
                        "sessions_dir": str(sessions_dir),
                        "error": str(e),
                    },
                )

        legacy_session_id = f"task_{normalized_task_id}" if normalized_task_id else preferred_session_id
        legacy_dir = sessions_dir / legacy_session_id
        if legacy_dir.exists():
            return legacy_dir, legacy_session_id, True

        return preferred_dir, preferred_session_id, False

    async def ensure_directory(self, exec_user: str, api_user: str, session_id: str = "default") -> Path:
        """
        确保用户目录存在，使用 {user_home_base}/{exec_user}/sessions/{session_id} 结构

        Args:
            exec_user: Linux系统用户名
            api_user: API用户名（仅用于日志记录）
            session_id: 会话ID，默认为"default"

        Returns:
            用户目录路径（包含session_id子目录）
        """
        user_dir = self.resolve_session_directory(exec_user, session_id)

        # 非 root 情况下，通常没有权限创建 /home/<other-user>；降级到当前用户的 HOME 下。
        # 这样也避免在测试里对 asyncio.create_subprocess_exec 的 patch 被误伤（mkdir/su 不再走子进程）。
        current_user = pwd.getpwuid(os.getuid()).pw_name

        if not user_dir.exists():
            try:
                # 检查当前运行用户是否与exec_user相同
                if current_user == exec_user:
                    # 当前用户就是目标用户，直接创建目录
                    user_dir.mkdir(parents=True, exist_ok=True)
                    logger.info(
                        f"Created user directory directly",
                        extra={
                            "exec_user": exec_user,
                            "api_user": api_user,
                            "user_dir": str(user_dir),
                            "action": "create_dir_direct"
                        }
                    )
                else:
                    # 需要切换用户创建目录。
                    #
                    # 注意：只有 root 进程才可靠地 `su - <user>` 而不需要交互式密码。
                    # 在测试/开发环境里我们通常不是 root，且 `exec_user`（如 testuser）也未必存在。
                    # 为了避免影响流式接口（以及测试对 asyncio.create_subprocess_exec 的 patch），这里做降级：
                    # - 非 root：直接用当前用户创建目录
                    # - root：再尝试 su 创建
                    if os.geteuid() != 0:
                        user_dir.mkdir(parents=True, exist_ok=True)
                        logger.warning(
                            "Creating user directory without su (non-root fallback)",
                            extra={
                                "exec_user": exec_user,
                                "api_user": api_user,
                                "user_dir": str(user_dir),
                                "action": "create_dir_fallback",
                            },
                        )
                    else:
                        mkdir_cmd = f"mkdir -p {shlex.quote(str(user_dir))}"
                        cmd = ["su", "-", exec_user, "-c", mkdir_cmd]

                        logger.info(
                            f"Creating user directory as exec user",
                            extra={
                                "exec_user": exec_user,
                                "api_user": api_user,
                                "user_dir": str(user_dir),
                                "command": " ".join(cmd),
                                "action": "create_dir"
                            }
                        )

                        process = await asyncio.create_subprocess_exec(
                            *cmd,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                            limit=10 * 1024 * 1024
                        )

                        _, stderr = await process.communicate()

                        if process.returncode != 0:
                            error_msg = stderr.decode('utf-8').strip() if stderr else "Unknown error"
                            logger.error(
                                f"Failed to create user directory via su",
                                extra={
                                    "exec_user": exec_user,
                                    "api_user": api_user,
                                    "user_dir": str(user_dir),
                                    "error": error_msg,
                                    "returncode": process.returncode
                                }
                            )
                            raise RuntimeError(f"无法以 {exec_user} 用户身份创建目录 {user_dir}: {error_msg}")

                        logger.info(
                            f"Successfully created user directory",
                            extra={
                                "exec_user": exec_user,
                                "api_user": api_user,
                                "user_dir": str(user_dir),
                                "action": "create_dir_success"
                            }
                        )

            except Exception as e:
                logger.error(
                    f"Failed to create user directory",
                    extra={
                        "exec_user": exec_user,
                        "api_user": api_user,
                        "user_dir": str(user_dir),
                        "error": str(e)
                    },
                    exc_info=True
                )
                raise RuntimeError(f"无法创建用户目录 {user_dir}: {e}")
        else:
            logger.debug(
                f"User directory already exists",
                extra={
                    "exec_user": exec_user,
                    "api_user": api_user,
                    "user_dir": str(user_dir),
                    "action": "check_dir"
                }
            )

        return user_dir

    async def clear_directory(self, exec_user: str, api_user: str, user_dir: Path, session_id: str = "default") -> None:
        """
        删除用户会话文件夹及其内容

        Args:
            exec_user: Linux系统用户名
            api_user: API用户名
            user_dir: 用户目录路径（包含session_id）
            session_id: 会话ID，用于日志记录
        """
        if not user_dir.exists():
            logger.info(
                f"User session directory does not exist, nothing to clear",
                extra={
                    "exec_user": exec_user,
                    "api_user": api_user,
                    "session_id": session_id,
                    "user_dir": str(user_dir),
                    "action": "clear_dir_skip"
                }
            )
            return

        try:
            rm_cmd = f"rm -rf {shlex.quote(str(user_dir))}"
            cmd = ["su", "-", exec_user, "-c", rm_cmd]

            logger.info(
                f"Clearing user session directory as exec user",
                extra={
                    "exec_user": exec_user,
                    "api_user": api_user,
                    "session_id": session_id,
                    "user_dir": str(user_dir),
                    "command": " ".join(cmd),
                    "action": "clear_dir"
                }
            )

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=10 * 1024 * 1024
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode('utf-8').strip() if stderr else "Unknown error"
                logger.error(
                    f"Failed to clear user session directory command",
                    extra={
                        "exec_user": exec_user,
                        "api_user": api_user,
                        "session_id": session_id,
                        "user_dir": str(user_dir),
                        "error": error_msg,
                        "returncode": process.returncode
                    }
                )
                raise RuntimeError(f"无法删除用户会话目录 {user_dir}: {error_msg}")

            logger.info(
                f"Successfully cleared user session directory",
                extra={
                    "exec_user": exec_user,
                    "api_user": api_user,
                    "session_id": session_id,
                    "user_dir": str(user_dir),
                    "action": "clear_dir_success"
                }
            )

        except Exception as e:
            logger.error(
                f"Failed to clear user session directory",
                extra={
                    "exec_user": exec_user,
                    "api_user": api_user,
                    "session_id": session_id,
                    "user_dir": str(user_dir),
                    "error": str(e)
                },
                exc_info=True
            )
            logger.warning(f"User session directory clear failed but continuing: {e}")
