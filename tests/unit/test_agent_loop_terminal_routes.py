from __future__ import annotations

import pytest

from src.nanobot.agent.loop import AgentLoop
from src.nanobot.bus.events import InboundMessage
from src.nanobot.providers.base import LLMProvider, LLMResponse


class CountingProvider(LLMProvider):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def chat(self, *args, **kwargs) -> LLMResponse:  # noqa: ANN002, ANN003
        self.calls += 1
        return LLMResponse(content="unexpected model call")

    def get_default_model(self) -> str:
        return "test-model"


class DummyBus:
    async def publish_outbound(self, _msg):
        return None


def test_records_rca_terminal_route_from_first_response_line(tmp_path):
    loop = AgentLoop(bus=DummyBus(), provider=CountingProvider(), workspace=tmp_path)
    session = loop.sessions.get_or_create("wecom:chat-1")

    loop._record_rca_terminal_route(session, "RETRY_REQUIRED\nwaiting for analyst evidence.")

    assert session.metadata["rca_terminal_route"]["route"] == "RETRY_REQUIRED"


@pytest.mark.asyncio
async def test_suppresses_late_teammate_message_after_terminal_route(tmp_path):
    provider = CountingProvider()
    loop = AgentLoop(bus=DummyBus(), provider=provider, workspace=tmp_path)
    session = loop.sessions.get_or_create("wecom:chat-1")
    session.metadata["rca_terminal_route"] = {"route": "RETRY_REQUIRED", "created_at_ms": 1}
    loop.sessions.save(session)

    msg = InboundMessage(
        channel="system",
        sender_id="subagent",
        chat_id="wecom:chat-1",
        content='<teammate-message from="hardware_analyst">late evidence</teammate-message>',
    )

    response = await loop._process_message(msg)

    assert response is None
    assert provider.calls == 0
