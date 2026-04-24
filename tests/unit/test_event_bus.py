# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio

from src.server.services.event_bus import EventEnvelope, EventBus
from src.server.services.domain_events import record_domain_event
from src.runtime.stores.db import Database


def test_event_bus_broadcast_round_trip():
    async def _run():
        bus = EventBus()
        queue = bus.subscribe("domain_event")
        bus.broadcast("domain_event.created", {"hello": "world"})
        envelope = await asyncio.wait_for(queue.get(), timeout=1)
        assert isinstance(envelope, EventEnvelope)
        assert envelope.event_type == "domain_event.created"
        assert envelope.payload["hello"] == "world"
        bus.unsubscribe(queue)

    asyncio.run(_run())


def test_record_domain_event_broadcasts_to_event_bus(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "events.db"))
    Database.reset_instances()

    async def _run():
        from src.server.services import event_bus as event_bus_module

        event_bus_module._event_bus = EventBus()
        queue = event_bus_module.get_event_bus().subscribe("domain_event")
        evt = record_domain_event(
            "task.created",
            "task",
            "task-123",
            actor="tester",
            payload={"k": "v"},
            task_id="task-123",
        )
        assert evt is not None
        envelope = await asyncio.wait_for(queue.get(), timeout=1)
        assert envelope.event_type == "domain_event.created"
        assert envelope.payload["aggregate_id"] == "task-123"
        event_bus_module.get_event_bus().unsubscribe(queue)

    asyncio.run(_run())
    Database.reset_instances()
