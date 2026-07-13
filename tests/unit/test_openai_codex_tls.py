from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.core.agent_runtime.providers import openai_codex_provider


@pytest.mark.asyncio
async def test_certificate_failure_does_not_retry_without_tls_verification(monkeypatch):
    monkeypatch.setattr(
        openai_codex_provider,
        "get_codex_token",
        lambda: SimpleNamespace(account_id="account", access="token"),
    )
    request = AsyncMock(side_effect=RuntimeError("CERTIFICATE_VERIFY_FAILED"))
    monkeypatch.setattr(openai_codex_provider, "_request_codex", request)
    provider = openai_codex_provider.OpenAICodexProvider()

    response = await provider.chat([{"role": "user", "content": "hello"}])

    assert response.finish_reason == "error"
    assert request.await_count == 1
    assert "verify" not in request.await_args.kwargs
