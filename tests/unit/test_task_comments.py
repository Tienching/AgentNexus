# -*- coding: utf-8 -*-
"""Tests for task comment API.

Ported from mission-control GET/POST /api/tasks/[id]/comments (commit 4ef91d4).

Covers:
- TaskComment / TaskCommentsResponse / CreateCommentRequest model shapes
- _build_comment_tree(): flat→threaded, ordering, orphan handling
- _load_comment(): happy path, missing key
- GET /tasks/{task_id}/comments: 404 on missing task, empty list, threaded result
- POST /tasks/{task_id}/comments: create top-level, create reply, 404 task, 400
  empty content, 400 missing parent, 400 reply-to-reply prevention
"""
from __future__ import annotations

import pytest
import time
from unittest.mock import MagicMock, patch

from src.server.routers.nexus_models import (
    TaskComment,
    TaskCommentsResponse,
    CreateCommentRequest,
)
from src.server.routers.nexus_tasks import (
    _comment_key,
    _comments_index_key,
    _load_comment,
    _build_comment_tree,
    get_task_comments,
    create_task_comment,
)


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestTaskCommentModel:
    def test_required_fields(self):
        c = TaskComment(id="c1", task_id="t1", author="alice", content="hello", created_at=1.0)
        assert c.id == "c1"
        assert c.task_id == "t1"
        assert c.author == "alice"
        assert c.content == "hello"
        assert c.created_at == 1.0

    def test_parent_id_defaults_none(self):
        c = TaskComment(id="c1", task_id="t1", author="alice", content="hello", created_at=1.0)
        assert c.parent_id is None

    def test_mentions_and_replies_default_empty(self):
        c = TaskComment(id="c1", task_id="t1", author="alice", content="hello", created_at=1.0)
        assert c.mentions == []
        assert c.replies == []


class TestTaskCommentsResponse:
    def test_defaults(self):
        r = TaskCommentsResponse(task_id="t1")
        assert r.comments == []
        assert r.total == 0
        assert r.task_id == "t1"


class TestCreateCommentRequest:
    def test_content_required(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CreateCommentRequest()  # type: ignore

    def test_author_defaults_to_user(self):
        r = CreateCommentRequest(content="hi")
        assert r.author == "user"

    def test_parent_id_optional(self):
        r = CreateCommentRequest(content="hi")
        assert r.parent_id is None

    def test_parent_id_accepted(self):
        r = CreateCommentRequest(content="hi", parent_id="p1")
        assert r.parent_id == "p1"


# ---------------------------------------------------------------------------
# _build_comment_tree()
# ---------------------------------------------------------------------------

class TestBuildCommentTree:
    def _c(self, cid, ts, parent_id=None):
        return TaskComment(
            id=cid, task_id="t", author="a", content="x",
            created_at=ts, parent_id=parent_id,
        )

    def test_empty_returns_empty(self):
        assert _build_comment_tree([]) == []

    def test_single_top_level(self):
        result = _build_comment_tree([self._c("c1", 1.0)])
        assert len(result) == 1
        assert result[0].id == "c1"
        assert result[0].replies == []

    def test_reply_attached_to_parent(self):
        parent = self._c("c1", 1.0)
        reply = self._c("c2", 2.0, parent_id="c1")
        result = _build_comment_tree([parent, reply])
        assert len(result) == 1  # only top-level in roots
        assert len(result[0].replies) == 1
        assert result[0].replies[0].id == "c2"

    def test_multiple_replies_sorted_by_time(self):
        parent = self._c("c1", 1.0)
        r1 = self._c("r1", 3.0, parent_id="c1")
        r2 = self._c("r2", 2.0, parent_id="c1")
        result = _build_comment_tree([parent, r1, r2])
        assert [r.id for r in result[0].replies] == ["r2", "r1"]

    def test_roots_sorted_by_time(self):
        c2 = self._c("c2", 2.0)
        c1 = self._c("c1", 1.0)
        result = _build_comment_tree([c2, c1])
        assert [c.id for c in result] == ["c1", "c2"]

    def test_orphan_reply_becomes_root(self):
        """Reply whose parent is missing is treated as top-level (graceful degradation)."""
        orphan = self._c("c2", 2.0, parent_id="MISSING")
        result = _build_comment_tree([orphan])
        assert len(result) == 1
        assert result[0].id == "c2"


# ---------------------------------------------------------------------------
# _load_comment()
# ---------------------------------------------------------------------------

class TestLoadComment:
    def test_returns_comment_from_redis(self):
        mock_redis = MagicMock()
        mock_redis.hgetall.return_value = {
            "id": "c1",
            "task_id": "t1",
            "author": "alice",
            "content": "hello world",
            "created_at": "1234567890.5",
            "parent_id": "",
        }
        comment = _load_comment(mock_redis, "user", "t1", "c1")
        assert comment is not None
        assert comment.id == "c1"
        assert comment.content == "hello world"
        assert comment.created_at == 1234567890.5
        assert comment.parent_id is None  # empty string becomes None

    def test_returns_none_when_missing(self):
        mock_redis = MagicMock()
        mock_redis.hgetall.return_value = {}
        assert _load_comment(mock_redis, "user", "t1", "missing") is None

    def test_preserves_parent_id(self):
        mock_redis = MagicMock()
        mock_redis.hgetall.return_value = {
            "id": "c2",
            "task_id": "t1",
            "author": "bob",
            "content": "reply",
            "created_at": "100.0",
            "parent_id": "c1",
        }
        comment = _load_comment(mock_redis, "user", "t1", "c2")
        assert comment.parent_id == "c1"


# ---------------------------------------------------------------------------
# GET /tasks/{task_id}/comments
# ---------------------------------------------------------------------------

class TestGetTaskCommentsRoute:
    def _make_queue(self, task=None, comment_ids=None, comments_by_id=None):
        """Build a mock TaskQueue with configurable Redis responses."""
        queue = MagicMock()
        queue.get_task.return_value = task
        mock_redis = MagicMock()
        queue._redis = mock_redis
        mock_redis.zrange.return_value = comment_ids or []

        def hgetall_side_effect(key):
            if comments_by_id is None:
                return {}
            for cid, data in (comments_by_id or {}).items():
                if cid in key:
                    return data
            return {}

        mock_redis.hgetall.side_effect = hgetall_side_effect
        return queue

    @pytest.mark.asyncio
    async def test_404_when_task_missing(self):
        from fastapi import HTTPException
        queue = self._make_queue(task=None)
        with patch("src.server.routers.nexus_tasks.get_task_queue", return_value=queue):
            with pytest.raises(HTTPException) as exc:
                await get_task_comments("nonexistent")
            assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_empty_list_for_task_with_no_comments(self):
        queue = self._make_queue(task=MagicMock(), comment_ids=[])
        with patch("src.server.routers.nexus_tasks.get_task_queue", return_value=queue):
            result = await get_task_comments("t1")
        assert result.comments == []
        assert result.total == 0

    @pytest.mark.asyncio
    async def test_returns_threaded_comments(self):
        now = time.time()
        comments_by_id = {
            "c1": {"id": "c1", "task_id": "t1", "author": "alice",
                   "content": "top", "created_at": str(now), "parent_id": ""},
            "c2": {"id": "c2", "task_id": "t1", "author": "bob",
                   "content": "reply", "created_at": str(now + 1), "parent_id": "c1"},
        }
        task = MagicMock()
        queue = self._make_queue(task=task, comment_ids=["c1", "c2"],
                                 comments_by_id=comments_by_id)
        with patch("src.server.routers.nexus_tasks.get_task_queue", return_value=queue):
            result = await get_task_comments("t1")
        assert result.total == 2
        # Thread tree: 1 root with 1 reply
        assert len(result.comments) == 1
        assert result.comments[0].id == "c1"
        assert len(result.comments[0].replies) == 1
        assert result.comments[0].replies[0].id == "c2"

    @pytest.mark.asyncio
    async def test_task_id_in_response(self):
        queue = self._make_queue(task=MagicMock(), comment_ids=[])
        with patch("src.server.routers.nexus_tasks.get_task_queue", return_value=queue):
            result = await get_task_comments("my-task-id")
        assert result.task_id == "my-task-id"


# ---------------------------------------------------------------------------
# POST /tasks/{task_id}/comments
# ---------------------------------------------------------------------------

class TestCreateTaskCommentRoute:
    def _make_queue(self, task=None):
        queue = MagicMock()
        queue.get_task.return_value = task
        mock_redis = MagicMock()
        queue._redis = mock_redis
        mock_redis.hgetall.return_value = {}  # no existing comments by default
        return queue

    @pytest.mark.asyncio
    async def test_404_when_task_missing(self):
        from fastapi import HTTPException
        queue = self._make_queue(task=None)
        with patch("src.server.routers.nexus_tasks.get_task_queue", return_value=queue):
            with pytest.raises(HTTPException) as exc:
                await create_task_comment("missing", CreateCommentRequest(content="hi"))
            assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_400_on_whitespace_only_content(self):
        from fastapi import HTTPException
        queue = self._make_queue(task=MagicMock())
        with patch("src.server.routers.nexus_tasks.get_task_queue", return_value=queue):
            with pytest.raises(HTTPException) as exc:
                await create_task_comment("t1", CreateCommentRequest(content="   "))
            assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_creates_top_level_comment(self):
        task = MagicMock()
        queue = self._make_queue(task=task)
        with patch("src.server.routers.nexus_tasks.get_task_queue", return_value=queue):
            result = await create_task_comment(
                "t1", CreateCommentRequest(content="Great work!", author="alice")
            )
        assert result.content == "Great work!"
        assert result.author == "alice"
        assert result.task_id == "t1"
        assert result.parent_id is None
        assert result.id  # UUID assigned
        # Redis hset and zadd called
        queue._redis.hset.assert_called_once()
        queue._redis.zadd.assert_called_once()

    @pytest.mark.asyncio
    async def test_creates_reply_when_parent_exists(self):
        task = MagicMock()
        queue = self._make_queue(task=task)
        # Mock parent comment lookup
        queue._redis.hgetall.return_value = {
            "id": "parent-id",
            "task_id": "t1",
            "author": "alice",
            "content": "parent comment",
            "created_at": "1.0",
            "parent_id": "",  # parent is top-level
        }
        with patch("src.server.routers.nexus_tasks.get_task_queue", return_value=queue):
            result = await create_task_comment(
                "t1", CreateCommentRequest(content="reply!", parent_id="parent-id")
            )
        assert result.parent_id == "parent-id"

    @pytest.mark.asyncio
    async def test_400_on_missing_parent(self):
        from fastapi import HTTPException
        task = MagicMock()
        queue = self._make_queue(task=task)
        queue._redis.hgetall.return_value = {}  # parent not found
        with patch("src.server.routers.nexus_tasks.get_task_queue", return_value=queue):
            with pytest.raises(HTTPException) as exc:
                await create_task_comment(
                    "t1", CreateCommentRequest(content="reply!", parent_id="ghost")
                )
            assert exc.value.status_code == 400
            assert "not found" in exc.value.detail.lower()

    @pytest.mark.asyncio
    async     def test_allows_reply_to_reply(self):
        """Nested replies are supported by MC-005 requirement."""
        task = MagicMock()
        queue = self._make_queue(task=task)
        # Parent is itself a reply (has parent_id set) — should still be accepted
        queue._redis.hgetall.return_value = {
            "id": "child-id",
            "task_id": "t1",
            "author": "alice",
            "content": "I'm a reply",
            "created_at": "1.0",
            "parent_id": "grandparent-id",
        }
        with patch("src.server.routers.nexus_tasks.get_task_queue", return_value=queue):
            result = await create_task_comment(
                "t1", CreateCommentRequest(content="deep reply!", parent_id="child-id")
            )
        assert result.parent_id == "child-id"

    @pytest.mark.asyncio
    async def test_default_author_is_user(self):
        task = MagicMock()
        queue = self._make_queue(task=task)
        with patch("src.server.routers.nexus_tasks.get_task_queue", return_value=queue):
            result = await create_task_comment("t1", CreateCommentRequest(content="hi"))
        assert result.author == "user"

    @pytest.mark.asyncio
    async def test_created_at_is_recent_timestamp(self):
        task = MagicMock()
        queue = self._make_queue(task=task)
        before = time.time()
        with patch("src.server.routers.nexus_tasks.get_task_queue", return_value=queue):
            result = await create_task_comment("t1", CreateCommentRequest(content="hi"))
        after = time.time()
        assert before <= result.created_at <= after

    @pytest.mark.asyncio
    async def test_extracts_mentions_and_persists_them(self):
        task = MagicMock()
        queue = self._make_queue(task=task)
        with patch("src.server.routers.nexus_tasks.get_task_queue", return_value=queue):
            result = await create_task_comment(
                "t1", CreateCommentRequest(content="ping @alice and @bob and @alice")
            )
        assert result.mentions == ["alice", "bob"]
        payload = queue._redis.hset.call_args[0][1]
        assert "mentions" in payload
        assert "alice" in payload["mentions"]
        assert "bob" in payload["mentions"]
