"""Message bus module for decoupled channel-agent communication."""

from src.nanobot.bus.events import InboundMessage, OutboundMessage
from src.nanobot.bus.queue import MessageBus

__all__ = ["MessageBus", "InboundMessage", "OutboundMessage"]
