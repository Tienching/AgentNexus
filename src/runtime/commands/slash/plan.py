# -*- coding: utf-8 -*-
"""Plan mode slash command extension.

Registers /plan subcommands for read-only exploration, plan submission,
approval, rejection, status, and exit.

Subcommands:
  /plan              — Enter plan mode (read-only exploration)
  /plan submit       — Submit a plan for approval (free text after --)
  /plan approve      — Approve the current plan and switch to execution
  /plan reject       — Reject the plan (remain in plan mode for revision)
  /plan status       — Show current plan mode status
  /plan exit         — Exit plan mode without approving
"""

from __future__ import annotations

from typing import Any, Dict

from .parser import (
    CommandSpec,
    OptionDef,
    register_slash_command_specs,
)
from .handler import (
    register_slash_command_handler,
    register_slash_extension_loader,
)


# ---------------------------------------------------------------------------
# Command specs
# ---------------------------------------------------------------------------

_PLAN_SPECS = [
    CommandSpec(
        cmd="plan",
        subcmd="enter",
        options=(),
        allow_free_text=False,
    ),
    CommandSpec(
        cmd="plan",
        subcmd="submit",
        options=(),
        allow_free_text=True,
        free_text_required=True,
    ),
    CommandSpec(
        cmd="plan",
        subcmd="approve",
        options=(),
        allow_free_text=False,
    ),
    CommandSpec(
        cmd="plan",
        subcmd="reject",
        options=(),
        allow_free_text=False,
    ),
    CommandSpec(
        cmd="plan",
        subcmd="status",
        options=(),
        allow_free_text=False,
    ),
    CommandSpec(
        cmd="plan",
        subcmd="exit",
        options=(),
        allow_free_text=False,
    ),
]


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def _get_agent_loop():
    """Get the AgentLoop instance from the server runtime."""
    try:
        from src.server.app import get_agent_loop
        return get_agent_loop()
    except Exception:
        return None


def _handle_plan_enter(handler, parsed, ctx: Dict[str, Any]) -> str:
    loop = _get_agent_loop()
    if loop is None:
        return "## Error\n\nAgent loop not available."
    if loop._plan_mode:
        return "## Already in Plan Mode\n\nYou are already in plan mode. Use `/plan submit -- <plan>` to submit a plan, or `/plan exit` to exit."
    loop.enter_plan_mode()
    return (
        "## Plan Mode Activated\n\n"
        "You are now in **plan mode** — only read-only tools are allowed.\n\n"
        "- Explore the codebase freely (read files, list dirs, search)\n"
        "- No writes, executions, or network calls permitted\n"
        "- When ready, submit your plan: `/plan submit -- <your plan>`\n"
        "- To exit without a plan: `/plan exit`"
    )


def _handle_plan_submit(handler, parsed, ctx: Dict[str, Any]) -> str:
    loop = _get_agent_loop()
    if loop is None:
        return "## Error\n\nAgent loop not available."
    content = parsed.free_text.strip()
    if not content:
        return "## Error\n\nPlan content is required. Usage: `/plan submit -- <plan text>`"
    if not loop._plan_mode:
        return "## Error\n\nNot in plan mode. Use `/plan` to enter plan mode first."
    loop.submit_plan(content)
    return (
        "## Plan Submitted\n\n"
        f"Your plan has been submitted for approval.\n\n"
        f"---\n\n{content}\n\n---\n\n"
        "Use `/plan approve` to approve and switch to execution mode, "
        "or `/plan reject` to revise."
    )


def _handle_plan_approve(handler, parsed, ctx: Dict[str, Any]) -> str:
    loop = _get_agent_loop()
    if loop is None:
        return "## Error\n\nAgent loop not available."
    if not loop._plan_mode:
        return "## Error\n\nNot in plan mode."
    if loop._plan_content is None:
        return "## Error\n\nNo plan has been submitted yet. Use `/plan submit -- <plan>` first."
    plan_text = loop._plan_content
    loop.approve_plan()
    return (
        "## Plan Approved — Execution Mode\n\n"
        "The plan has been approved. You are now in **execution mode** with full tool access.\n\n"
        f"---\n\n{plan_text}\n\n---"
    )


def _handle_plan_reject(handler, parsed, ctx: Dict[str, Any]) -> str:
    loop = _get_agent_loop()
    if loop is None:
        return "## Error\n\nAgent loop not available."
    if not loop._plan_mode:
        return "## Error\n\nNot in plan mode."
    loop.reject_plan()
    return (
        "## Plan Rejected\n\n"
        "The plan has been rejected. You remain in **plan mode** — "
        "revise and resubmit with `/plan submit -- <revised plan>`."
    )


def _handle_plan_status(handler, parsed, ctx: Dict[str, Any]) -> str:
    loop = _get_agent_loop()
    if loop is None:
        return "## Plan Status\n\nAgent loop not available.\n\n- **Plan Mode:** unavailable\n- **Permission Mode:** unknown"
    status = loop.get_plan_status()
    mode_label = "ACTIVE" if status["plan_mode"] else "inactive"
    content = status.get("plan_content")
    approved = status.get("plan_approved", False)
    perm = status.get("permission_mode", "unknown")
    lines = [
        "## Plan Mode Status\n",
        f"- **Plan Mode:** {mode_label}",
        f"- **Permission Mode:** {perm}",
    ]
    if status["plan_mode"]:
        if content:
            lines.append(f"- **Plan Submitted:** yes")
            lines.append(f"- **Plan Approved:** {'yes' if approved else 'no'}")
            lines.append(f"\n---\n\n{content}\n\n---")
        else:
            lines.append("- **Plan Submitted:** no")
            lines.append("\nUse `/plan submit -- <plan>` to submit your plan.")
    return "\n".join(lines)


def _handle_plan_exit(handler, parsed, ctx: Dict[str, Any]) -> str:
    loop = _get_agent_loop()
    if loop is None:
        return "## Error\n\nAgent loop not available."
    if not loop._plan_mode:
        return "## Not in Plan Mode\n\nYou are not currently in plan mode."
    loop.exit_plan_mode()
    return "## Plan Mode Exited\n\nYou have left plan mode. Full tool access restored."


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def _register_plan_commands() -> None:
    """Register all /plan command specs and handlers."""
    register_slash_command_specs(
        _PLAN_SPECS,
        command="plan",
        default_subcmd="enter",
    )
    register_slash_command_handler("plan", "enter", _handle_plan_enter)
    register_slash_command_handler("plan", "submit", _handle_plan_submit)
    register_slash_command_handler("plan", "approve", _handle_plan_approve)
    register_slash_command_handler("plan", "reject", _handle_plan_reject)
    register_slash_command_handler("plan", "status", _handle_plan_status)
    register_slash_command_handler("plan", "exit", _handle_plan_exit)


# Auto-register via extension loader
register_slash_extension_loader(_register_plan_commands)
