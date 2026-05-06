# -*- coding: utf-8 -*-
"""Unit tests for CallbackHandler.send_callback() retry logic.

Ported from mission-control src/lib/__tests__/setup-status.test.ts design:
  - Only retry on transient errors (network errors, timeouts, 5xx).
  - Immediately give up on 4xx client errors (permanent failures).

Tests use unittest.mock to patch httpx.AsyncClient so no real HTTP calls
are made.
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from src.server.services.callback_handler import CallbackHandler, CALLBACK_MAX_RETRIES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(status_code: int) -> MagicMock:
    """Build a minimal httpx.Response-like mock."""
    r = MagicMock()
    r.status_code = status_code
    return r


def _make_handler() -> CallbackHandler:
    return CallbackHandler()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestSendCallbackSuccess:
    @pytest.mark.asyncio
    async def test_returns_true_on_200(self):
        handler = _make_handler()
        mock_response = _make_response(200)

        with patch("src.server.services.callback_handler.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await handler.send_callback(
                "http://example.com/hook",
                ["hello world"],
            )

        assert result is True
        assert mock_client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_returns_true_on_201(self):
        handler = _make_handler()
        mock_response = _make_response(201)

        with patch("src.server.services.callback_handler.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await handler.send_callback(
                "http://example.com/hook",
                ["hello world"],
            )

        assert result is True


# ---------------------------------------------------------------------------
# 4xx — immediate failure, no retry
# ---------------------------------------------------------------------------

class TestSendCallbackClientErrors:
    @pytest.mark.parametrize("status_code", [400, 401, 403, 404, 409, 422, 429])
    @pytest.mark.asyncio
    async def test_4xx_returns_false_immediately(self, status_code: int):
        """4xx client errors are permanent — must not retry."""
        handler = _make_handler()
        mock_response = _make_response(status_code)

        with patch("src.server.services.callback_handler.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await handler.send_callback(
                "http://example.com/hook",
                ["hello world"],
            )

        assert result is False
        # Only ONE attempt — no retries for 4xx
        assert mock_client.post.call_count == 1, (
            f"HTTP {status_code} is a client error and must not be retried, "
            f"but got {mock_client.post.call_count} attempt(s)"
        )

    @pytest.mark.asyncio
    async def test_404_no_sleep_between_attempts(self):
        """Verify no asyncio.sleep is called when we short-circuit on 4xx."""
        handler = _make_handler()
        mock_response = _make_response(404)

        with patch("src.server.services.callback_handler.httpx.AsyncClient") as MockClient, \
             patch("src.server.services.callback_handler.asyncio.sleep") as mock_sleep:

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            await handler.send_callback("http://example.com/hook", ["msg"])

        mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# 5xx — retried up to CALLBACK_MAX_RETRIES times
# ---------------------------------------------------------------------------

class TestSendCallbackServerErrors:
    @pytest.mark.parametrize("status_code", [500, 502, 503, 504])
    @pytest.mark.asyncio
    async def test_5xx_retries_up_to_max(self, status_code: int):
        """5xx server errors are transient — must retry."""
        handler = _make_handler()
        mock_response = _make_response(status_code)

        with patch("src.server.services.callback_handler.httpx.AsyncClient") as MockClient, \
             patch("src.server.services.callback_handler.asyncio.sleep", new_callable=AsyncMock):

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await handler.send_callback(
                "http://example.com/hook",
                ["hello world"],
            )

        assert result is False
        assert mock_client.post.call_count == CALLBACK_MAX_RETRIES, (
            f"HTTP {status_code} should be retried {CALLBACK_MAX_RETRIES} times"
        )

    @pytest.mark.asyncio
    async def test_5xx_then_200_succeeds(self):
        """Transient 5xx followed by 200 on retry → success."""
        handler = _make_handler()

        responses = [_make_response(503), _make_response(200)]
        call_index = [0]

        async def side_effect(*args, **kwargs):
            resp = responses[call_index[0]]
            call_index[0] += 1
            return resp

        with patch("src.server.services.callback_handler.httpx.AsyncClient") as MockClient, \
             patch("src.server.services.callback_handler.asyncio.sleep", new_callable=AsyncMock):

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=side_effect)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await handler.send_callback(
                "http://example.com/hook",
                ["hello world"],
            )

        assert result is True
        assert mock_client.post.call_count == 2


# ---------------------------------------------------------------------------
# Network / timeout errors — retried
# ---------------------------------------------------------------------------

class TestSendCallbackNetworkErrors:
    @pytest.mark.asyncio
    async def test_timeout_retries_up_to_max(self):
        import httpx
        handler = _make_handler()

        with patch("src.server.services.callback_handler.httpx.AsyncClient") as MockClient, \
             patch("src.server.services.callback_handler.asyncio.sleep", new_callable=AsyncMock):

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await handler.send_callback(
                "http://example.com/hook",
                ["hello world"],
            )

        assert result is False
        assert mock_client.post.call_count == CALLBACK_MAX_RETRIES

    @pytest.mark.asyncio
    async def test_request_error_retries_up_to_max(self):
        import httpx
        handler = _make_handler()

        with patch("src.server.services.callback_handler.httpx.AsyncClient") as MockClient, \
             patch("src.server.services.callback_handler.asyncio.sleep", new_callable=AsyncMock):

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                side_effect=httpx.RequestError("connection refused", request=MagicMock())
            )
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await handler.send_callback(
                "http://example.com/hook",
                ["hello world"],
            )

        assert result is False
        assert mock_client.post.call_count == CALLBACK_MAX_RETRIES

    @pytest.mark.asyncio
    async def test_network_error_then_200_succeeds(self):
        import httpx
        handler = _make_handler()

        call_count = [0]

        async def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise httpx.RequestError("first attempt fails", request=MagicMock())
            return _make_response(200)

        with patch("src.server.services.callback_handler.httpx.AsyncClient") as MockClient, \
             patch("src.server.services.callback_handler.asyncio.sleep", new_callable=AsyncMock):

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=side_effect)
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await handler.send_callback(
                "http://example.com/hook",
                ["hello world"],
            )

        assert result is True
        assert call_count[0] == 2


# ---------------------------------------------------------------------------
# Guard: no response_url or no messages
# ---------------------------------------------------------------------------

class TestSendCallbackGuards:
    @pytest.mark.asyncio
    async def test_empty_response_url_returns_false_no_http(self):
        handler = _make_handler()
        with patch("src.server.services.callback_handler.httpx.AsyncClient") as MockClient:
            result = await handler.send_callback("", ["hello"])
        assert result is False
        MockClient.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_messages_returns_false_no_http(self):
        handler = _make_handler()
        with patch("src.server.services.callback_handler.httpx.AsyncClient") as MockClient:
            result = await handler.send_callback("http://example.com/hook", [])
        assert result is False
        MockClient.assert_not_called()


class TestAGUIEventsToMarkdown:
    def test_tool_start_uses_standard_tool_call_name(self):
        handler = _make_handler()

        parts = handler.agui_events_to_markdown([
            'data: {"type":"TOOL_CALL_START","toolCallId":"tool-1","toolCallName":"Bash: 收集系统状态"}\n\n',
        ])

        assert parts == ["\n🛠️ **[调用工具: Bash: 收集系统状态]**\n"]
