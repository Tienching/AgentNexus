# -*- coding: utf-8 -*-
"""In-process event bus for lightweight realtime control-plane updates."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Dict, List, Optional


@dataclass
class EventEnvelope:
    event_type: str
    payload: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "payload": self.payload,
            "created_at": self.created_at,
        }


@dataclass
class _Subscriber:
    queue: asyncio.Queue
    topic_prefix: Optional[str]
    loop: asyncio.AbstractEventLoop


class EventBus:
    def __init__(self) -> None:
        self._subs: List[_Subscriber] = []
        self._lock = Lock()

    def subscribe(self, topic_prefix: Optional[str] = None, *, maxsize: int = 256) -> asyncio.Queue:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        with self._lock:
            self._subs.append(_Subscriber(queue=queue, topic_prefix=topic_prefix, loop=loop))
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._subs = [sub for sub in self._subs if sub.queue is not queue]

    def broadcast(self, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
        envelope = EventEnvelope(event_type=event_type, payload=payload or {})
        with self._lock:
            subscribers = list(self._subs)
        for sub in subscribers:
            if sub.topic_prefix and not event_type.startswith(sub.topic_prefix):
                continue
            def _put_nowait(subscriber: _Subscriber = sub, item: EventEnvelope = envelope) -> None:
                try:
                    subscriber.queue.put_nowait(item)
                except asyncio.QueueFull:
                    try:
                        subscriber.queue.get_nowait()
                    except Exception:
                        pass
                    try:
                        subscriber.queue.put_nowait(item)
                    except Exception:
                        pass
            try:
                sub.loop.call_soon_threadsafe(_put_nowait)
            except RuntimeError:
                continue


_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus
