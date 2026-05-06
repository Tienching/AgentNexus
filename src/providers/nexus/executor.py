# -*- coding: utf-8 -*-
"""NexusExecutor — runs nexus AgentLoop in-process.

The key challenge is bridging nexus's *callback-based* streaming with
agent-nexus's *AsyncGenerator-based* streaming.  We use an
``asyncio.Queue`` as a unidirectional pipe:

    AgentLoop callbacks  ──push──▶  asyncio.Queue  ──pull──▶  yield
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator

from src.providers.base import BaseExecutor, RequestContext
from src.providers.nexus.event_schema import (
    ErrorEvent,
    NexusEvent,
    TextDeltaEvent,
    TextEndEvent,
    TextStartEvent,
    ToolEndEvent,
    ToolResultEvent,
    ToolStartEvent,
)
from src.providers.nexus.session_bridge import (
    to_nexus_channel_and_chat,
    to_nexus_session_key,
)

logger = logging.getLogger(__name__)

# Sentinel object to signal "no more events"
_SENTINEL = object()


# ---------------------------------------------------------------------------
# AgentLoop pool – keeps one loop instance per workspace
# ---------------------------------------------------------------------------

class _NexusPool:
    """Process-level pool of AgentLoop instances, keyed by workspace."""

    _instances: dict[str, Any] = {}  # workspace_str -> AgentLoop
    _lock = asyncio.Lock() if hasattr(asyncio, "Lock") else None

    @classmethod
    async def get_or_create(cls, workspace: str, model: str | None = None) -> Any:
        """Return (or lazily create) an AgentLoop for *workspace*."""
        if cls._lock is None:
            cls._lock = asyncio.Lock()

        async with cls._lock:
            if workspace in cls._instances:
                return cls._instances[workspace]

            loop = await cls._create_loop(workspace, model)
            cls._instances[workspace] = loop
            return loop

    @classmethod
    async def _create_loop(cls, workspace: str, model: str | None) -> Any:
        """Construct a fresh AgentLoop."""
        try:
            from src.nanobot.config.loader import load_config
            from src.nanobot.bus.queue import MessageBus
            from src.nanobot.agent.loop import AgentLoop

            # load_config() uses ~/.nexus/config.json by default
            config = load_config()
            # model priority: explicit override > nexus config > provider default
            effective_model = model or config.agents.defaults.model
            provider = cls._make_provider(config, effective_model)
            bus = MessageBus()

            effective_model = effective_model or provider.get_default_model()

            loop = AgentLoop(
                bus=bus,
                provider=provider,
                workspace=Path(workspace),
                model=effective_model,
                max_iterations=config.agents.defaults.max_tool_iterations,
                web_search_config=config.tools.web.search,
                web_proxy=config.tools.web.proxy,
                exec_config=config.tools.exec,
                restrict_to_workspace=config.tools.restrict_to_workspace,
                mcp_servers=config.tools.mcp_servers or {},
                timezone=config.agents.defaults.timezone,
            )

            # Inject agent-nexus skills (orchestrator, mission) via SkillsLoader
            nexus_skills_dir = Path(__file__).resolve().parents[3] / "prompts" / "skills"
            if nexus_skills_dir.exists():
                loop.context.skills.extra_skills_dirs = [nexus_skills_dir]
                logger.info("Injected nexus skills from %s", nexus_skills_dir)

            logger.info("Created AgentLoop for workspace=%s model=%s", workspace, effective_model)
            return loop

        except Exception:
            logger.exception("Failed to create AgentLoop for workspace=%s", workspace)
            raise

    @staticmethod
    def _make_provider(config: Any, model_override: str | None = None) -> Any:
        """Create the appropriate LLM provider from nexus config.

        Extracted from nexus/cli/commands.py::_make_provider — we need this
        because cli/ was excluded from the source merge.
        """
        from src.nanobot.providers.base import GenerationSettings
        from src.nanobot.providers.registry import find_by_name

        model = model_override or config.agents.defaults.model
        provider_name = config.get_provider_name(model)
        p = config.get_provider(model)
        spec = find_by_name(provider_name) if provider_name else None
        backend = spec.backend if spec else "openai_compat"

        if backend == "openai_codex":
            from src.nanobot.providers.openai_codex_provider import OpenAICodexProvider
            provider = OpenAICodexProvider(default_model=model)
        elif backend == "azure_openai":
            from src.nanobot.providers.azure_openai_provider import AzureOpenAIProvider
            provider = AzureOpenAIProvider(
                api_key=p.api_key if p else None,
                api_base=p.api_base if p else None,
                default_model=model,
            )
        elif backend == "anthropic":
            from src.nanobot.providers.anthropic_provider import AnthropicProvider
            provider = AnthropicProvider(
                api_key=p.api_key if p else None,
                api_base=config.get_api_base(model),
                default_model=model,
                extra_headers=p.extra_headers if p else None,
            )
        else:
            from src.nanobot.providers.openai_compat_provider import OpenAICompatProvider
            provider = OpenAICompatProvider(
                api_key=p.api_key if p else None,
                api_base=config.get_api_base(model),
                default_model=model,
                extra_headers=p.extra_headers if p else None,
                spec=spec,
            )

        defaults = config.agents.defaults
        provider.generation = GenerationSettings(
            temperature=defaults.temperature,
            max_tokens=defaults.max_tokens,
            reasoning_effort=defaults.reasoning_effort,
        )
        return provider

    @classmethod
    async def close_all(cls) -> None:
        """Shutdown all loops (call on app teardown)."""
        for ws, loop in list(cls._instances.items()):
            try:
                await loop.close_mcp()
            except Exception:
                logger.warning("Error closing AgentLoop for %s", ws, exc_info=True)
        cls._instances.clear()


# ---------------------------------------------------------------------------
# NexusExecutor
# ---------------------------------------------------------------------------

class NexusExecutor(BaseExecutor):
    """In-process executor backed by nexus's AgentLoop.

    Each ``execute()`` call:
    1.  Obtains (or creates) an AgentLoop from the pool.
    2.  Wires callback functions that push events into an ``asyncio.Queue``.
    3.  Spawns ``AgentLoop.process_direct()`` as a background task.
    4.  Yields serialised :class:`NexusEvent` JSON lines from the queue.
    """

    def __init__(self, *, config: Any = None):
        super().__init__(config=config)
        self._workspace: str | None = None
        self._model: str | None = None

        # Resolve workspace from config
        if config:
            self._workspace = (
                getattr(config, "nexus_workspace", None)
                or getattr(config, "nanobot_workspace", None)
                or self._workspace
            )
        if not self._workspace:
            self._workspace = os.environ.get(
                "NEXUS_WORKSPACE",
                os.environ.get("NANOBOT_WORKSPACE", str(Path.home() / "Projects")),
            )

        if config:
            self._model = (
                getattr(config, "nexus_model", None)
                or getattr(config, "nanobot_model", None)
                or self._model
            )

    # ── BaseExecutor interface ────────────────────────────────────────

    def _build_command(self, context: RequestContext) -> list[str]:
        """Not used — we run in-process, not via subprocess."""
        return []

    async def execute(
        self,
        request: Any,
        exec_user: str = "default",
        output_format: str = "raw",
    ) -> AsyncGenerator[str, None]:
        """Execute a user message through nexus's AgentLoop.

        Yields one JSON-encoded :class:`NexusEvent` per line.
        """
        content = getattr(request, 'content', '') or ''
        session_id = getattr(request, 'session_id', 'default') or 'default'
        cwd = getattr(request, 'cwd', None)
        model_override = getattr(request, 'model', None)

        # Resolve workspace (request may override)
        workspace = cwd or self._workspace or str(Path.home() / "Projects")

        try:
            agent_loop = await _NexusPool.get_or_create(workspace, model_override or self._model)
        except Exception as e:
            err = ErrorEvent(message=f"Failed to initialise nexus: {e}")
            yield json.dumps({"type": err.type, "message": err.message})
            return

        queue: asyncio.Queue[NexusEvent | object] = asyncio.Queue(maxsize=512)

        session_key = to_nexus_session_key(session_id)
        channel, chat_id = to_nexus_channel_and_chat(session_id)

        # ── Build callbacks ───────────────────────────────────────────
        message_id = f"msg_{uuid.uuid4().hex[:12]}"
        _text_started = False

        async def _on_stream(delta: str) -> None:
            nonlocal _text_started
            if not _text_started:
                _text_started = True
                await queue.put(TextStartEvent(message_id=message_id))
            await queue.put(TextDeltaEvent(message_id=message_id, delta=delta))

        async def _on_stream_end(*, resuming: bool = False) -> None:
            nonlocal _text_started
            if _text_started:
                await queue.put(TextEndEvent(message_id=message_id))
                _text_started = False

        async def _on_tool_start(name: str, tool_call_id: str, arguments: dict) -> None:
            await queue.put(ToolStartEvent(
                tool_call_id=tool_call_id,
                name=name,
                arguments=arguments,
            ))

        async def _on_tool_end(tool_call_id: str, result_text: str) -> None:
            await queue.put(ToolResultEvent(
                tool_call_id=tool_call_id,
                content=result_text[:4000],
            ))
            await queue.put(ToolEndEvent(tool_call_id=tool_call_id))

        # ── Background task ───────────────────────────────────────────
        async def _run() -> None:
            try:
                await agent_loop.process_direct(
                    content=content,
                    session_key=session_key,
                    channel=channel,
                    chat_id=chat_id,
                    on_stream=_on_stream,
                    on_stream_end=_on_stream_end,
                    on_tool_start=_on_tool_start,
                    on_tool_end=_on_tool_end,
                )
            except asyncio.CancelledError:
                await queue.put(ErrorEvent(message="Request cancelled"))
            except Exception as exc:
                logger.exception("AgentLoop.process_direct failed")
                await queue.put(ErrorEvent(message=str(exc)))
            finally:
                await queue.put(_SENTINEL)

        task = asyncio.create_task(_run())

        # ── Drain queue ───────────────────────────────────────────────
        try:
            while True:
                item = await queue.get()
                if item is _SENTINEL:
                    break
                # Serialise event to JSON line
                if isinstance(item, NexusEvent):
                    yield _serialise_event(item)
        except (asyncio.CancelledError, GeneratorExit):
            task.cancel()
            raise
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialise_event(event: NexusEvent) -> str:
    """Serialise a NexusEvent dataclass to a JSON string (one line)."""
    d: dict[str, Any] = {"type": event.type}
    # Copy all public attributes except 'type'
    for attr in event.__dataclass_fields__:
        if attr != "type":
            d[attr] = getattr(event, attr)
    return json.dumps(d, ensure_ascii=False)


NanobotExecutor = NexusExecutor
_NanobotPool = _NexusPool
_LoopPool = _NexusPool

__all__ = [
    "NexusExecutor",
    "NanobotExecutor",
    "_NexusPool",
    "_NanobotPool",
    "_LoopPool",
    "_serialise_event",
]
