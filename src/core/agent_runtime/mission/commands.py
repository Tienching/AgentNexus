"""Slash command handlers for /mission."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.core.agent_runtime.bus.events import OutboundMessage
from src.core.agent_runtime.command.router import CommandContext

if TYPE_CHECKING:
    from src.core.agent_runtime.mission.service import MissionService


def _get_service(ctx: CommandContext) -> MissionService | None:
    """Get MissionService from the loop."""
    return getattr(ctx.loop, "mission_service", None)


async def cmd_mission(ctx: CommandContext) -> OutboundMessage:
    """Handle /mission subcommands."""
    args = ctx.args.strip() if ctx.args else ""
    parts = args.split(None, 1)
    subcmd = parts[0].lower() if parts else "help"
    rest = parts[1] if len(parts) > 1 else ""

    service = _get_service(ctx)
    if not service:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="Mission service is not available.",
        )

    try:
        if subcmd == "start":
            return await _cmd_start(ctx, service, rest)
        elif subcmd == "plan":
            return await _cmd_plan(ctx, service, rest)
        elif subcmd == "approve":
            return await _cmd_approve(ctx, service, rest)
        elif subcmd == "status":
            return await _cmd_status(ctx, service, rest)
        elif subcmd == "list":
            return await _cmd_list(ctx, service)
        elif subcmd == "pause":
            return await _cmd_pause(ctx, service, rest)
        elif subcmd == "resume":
            return await _cmd_resume(ctx, service, rest)
        elif subcmd == "cancel":
            return await _cmd_cancel(ctx, service, rest)
        elif subcmd == "log":
            return await _cmd_log(ctx, service, rest)
        else:
            return _cmd_help(ctx)
    except Exception as e:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=f"Mission error: {e}",
        )


async def _cmd_plan(ctx: CommandContext, service: MissionService, goal: str) -> OutboundMessage:
    """Plan a mission without executing (requires approval to start)."""
    if not goal:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="Usage: /mission plan <goal description>",
        )

    from src.core.agent_runtime.mission.types import MissionOrigin

    origin = MissionOrigin(channel=ctx.msg.channel, chat_id=ctx.msg.chat_id)
    mission = await service.plan_mission(goal=goal, origin=origin)

    # Format milestone summary for review
    plan_lines = []
    for ms in mission.milestones:
        plan_lines.append(f"  **{ms.title}** ({len(ms.tasks)} tasks)")
        for task in ms.tasks:
            plan_lines.append(f"    - [{task.role}] {task.title}")
    plan_summary = "\n".join(plan_lines)

    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=(
            f"📋 Mission planned!\n\n"
            f"**ID:** `{mission.id}`\n"
            f"**Goal:** {mission.goal}\n"
            f"**Type:** {mission.mission_type}\n"
            f"**Plan:** {len(mission.milestones)} milestones, {mission.total_tasks} tasks\n\n"
            f"### Plan Overview\n{plan_summary}\n\n"
            f"Review the plan, then run `/mission approve {mission.id}` to start execution."
        ),
    )


async def _cmd_approve(ctx: CommandContext, service: MissionService, mission_id: str) -> OutboundMessage:
    """Approve a planned mission and start execution."""
    if not mission_id:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="Usage: /mission approve <mission_id>",
        )
    ok = await service.confirm_mission(mission_id.strip())
    if ok:
        content = f"✅ Mission `{mission_id}` approved and started!"
    else:
        content = f"Cannot approve mission `{mission_id}`. It may not exist or is not in 'planned' status."
    return OutboundMessage(channel=ctx.msg.channel, chat_id=ctx.msg.chat_id, content=content)


async def _cmd_start(ctx: CommandContext, service: MissionService, goal: str) -> OutboundMessage:
    if not goal:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="Usage: /mission start <goal description>",
        )

    from src.core.agent_runtime.mission.types import MissionOrigin

    origin = MissionOrigin(channel=ctx.msg.channel, chat_id=ctx.msg.chat_id)
    mission = await service.start_mission(goal=goal, origin=origin)

    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=(
            f"🚀 Mission started!\n\n"
            f"**ID:** `{mission.id}`\n"
            f"**Goal:** {mission.goal}\n"
            f"**Type:** {mission.mission_type}\n"
            f"**Plan:** {len(mission.milestones)} milestones, {mission.total_tasks} tasks\n\n"
            f"Use `/mission status {mission.id}` to check progress."
        ),
    )


async def _cmd_status(ctx: CommandContext, service: MissionService, mission_id: str) -> OutboundMessage:
    if not mission_id:
        # Show most recent active mission
        missions = service.list_missions(include_completed=False)
        if not missions:
            missions = service.list_missions()
        if not missions:
            return OutboundMessage(
                channel=ctx.msg.channel,
                chat_id=ctx.msg.chat_id,
                content="No missions found.",
            )
        mission = missions[-1]
    else:
        mission = service.get_mission(mission_id.strip())
        if not mission:
            return OutboundMessage(
                channel=ctx.msg.channel,
                chat_id=ctx.msg.chat_id,
                content=f"Mission `{mission_id}` not found.",
            )

    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=service.format_status(mission),
    )


async def _cmd_list(ctx: CommandContext, service: MissionService) -> OutboundMessage:
    missions = service.list_missions()
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=service.format_list(missions),
    )


async def _cmd_pause(ctx: CommandContext, service: MissionService, mission_id: str) -> OutboundMessage:
    if not mission_id:
        return OutboundMessage(
            channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
            content="Usage: /mission pause <mission_id>",
        )
    ok = await service.pause_mission(mission_id.strip())
    content = f"⏸️ Mission `{mission_id}` paused." if ok else f"Cannot pause mission `{mission_id}`."
    return OutboundMessage(channel=ctx.msg.channel, chat_id=ctx.msg.chat_id, content=content)


async def _cmd_resume(ctx: CommandContext, service: MissionService, mission_id: str) -> OutboundMessage:
    if not mission_id:
        return OutboundMessage(
            channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
            content="Usage: /mission resume <mission_id>",
        )
    ok = await service.resume_mission(mission_id.strip())
    content = f"▶️ Mission `{mission_id}` resumed." if ok else f"Cannot resume mission `{mission_id}`."
    return OutboundMessage(channel=ctx.msg.channel, chat_id=ctx.msg.chat_id, content=content)


async def _cmd_cancel(ctx: CommandContext, service: MissionService, mission_id: str) -> OutboundMessage:
    if not mission_id:
        return OutboundMessage(
            channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
            content="Usage: /mission cancel <mission_id>",
        )
    ok = await service.cancel_mission(mission_id.strip())
    content = f"🚫 Mission `{mission_id}` cancelled." if ok else f"Cannot cancel mission `{mission_id}`."
    return OutboundMessage(channel=ctx.msg.channel, chat_id=ctx.msg.chat_id, content=content)


async def _cmd_log(ctx: CommandContext, service: MissionService, mission_id: str) -> OutboundMessage:
    if not mission_id:
        return OutboundMessage(
            channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
            content="Usage: /mission log <mission_id>",
        )
    mission = service.get_mission(mission_id.strip())
    if not mission:
        return OutboundMessage(
            channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
            content=f"Mission `{mission_id}` not found.",
        )
    log_text = "\n".join(mission.log[-30:]) if mission.log else "No log entries."
    return OutboundMessage(
        channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
        content=f"## Mission Log: `{mission.id}`\n\n```\n{log_text}\n```",
    )


def _cmd_help(ctx: CommandContext) -> OutboundMessage:
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=(
            "## 🎯 Mission Commands\n\n"
            "`/mission plan <goal>` — Plan a mission (review before execution)\n"
            "`/mission approve <id>` — Approve and start a planned mission\n"
            "`/mission start <goal>` — Plan and immediately start a mission\n"
            "`/mission status [id]` — Show mission status\n"
            "`/mission list` — List all missions\n"
            "`/mission pause <id>` — Pause a running mission\n"
            "`/mission resume <id>` — Resume a paused mission\n"
            "`/mission cancel <id>` — Cancel a mission\n"
            "`/mission log <id>` — View mission log\n"
            "`/mission help` — Show this help"
        ),
        metadata={"render_as": "text"},
    )
