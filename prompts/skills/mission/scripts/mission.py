#!/usr/bin/env python3
"""
Mission CLI — autonomous goal execution via nexus's mission system.

Subcommands:
    plan      Decompose goal into milestones/tasks (status=planned)
    start     Plan + auto-approve + start execution
    approve   Approve a planned mission and start execution
    status    Show mission progress (milestones, tasks, timing)
    list      List all missions (compact)
    cancel    Cancel a mission
    pause     Pause a running mission
    resume    Resume a paused mission
    log       View mission log entries

All output is compact and LLM-friendly.
"""

import argparse
import asyncio
import os
import sys
import textwrap

# ── Path setup ─────────────────────────────────────────────────────
# Add project root to path so we can import from src.server
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, "..", "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ── Lazy bridge accessor ──────────────────────────────────────────
def _get_bridge():
    """Get MissionBridge instance (lazy import to avoid import errors at parse time)."""
    from src.server.services.mission_bridge import MissionBridge
    return MissionBridge.get_instance()


# ── Formatters ────────────────────────────────────────────────────
def _format_plan(data: dict) -> str:
    """Format a mission plan for display."""
    lines = [
        f"Mission: {data['id']}",
        f"Goal: {data['goal']}",
        f"Status: {data['status']}",
        f"Plan: {len(data['milestones'])} milestones, {data['total_tasks']} tasks",
    ]
    for ms in data["milestones"]:
        deps = f" (depends: {', '.join(ms['depends_on'])})" if ms.get("depends_on") else ""
        lines.append(f"  [{ms['id']}] {ms['title']}{deps}")
        for t in ms["tasks"]:
            role_tag = f"[{t['role']:8s}]"
            t_deps = f" deps=[{','.join(t['depends_on'])}]" if t.get("depends_on") else ""
            lines.append(f"    {role_tag} {t['title']}{t_deps}")
    return "\n".join(lines)


# ── Subcommands ───────────────────────────────────────────────────

async def cmd_plan(args):
    """Decompose goal into milestones/tasks without executing."""
    bridge = _get_bridge()
    data = await bridge.plan(
        goal=args.goal,
        workspace=args.workspace,
    )
    print(_format_plan(data))


async def cmd_start(args):
    """Plan + auto-approve + start execution."""
    bridge = _get_bridge()
    data = await bridge.start(
        goal=args.goal,
        workspace=args.workspace,
    )
    print(_format_plan(data))
    print(f"\nExecution started. Monitor with: mission.py status {data['id']}")


async def cmd_approve(args):
    """Approve a planned mission and start execution."""
    bridge = _get_bridge()
    ok = await bridge.approve(args.mission_id)
    if ok:
        print(f"[OK] Mission {args.mission_id} approved and started")
    else:
        print(f"[ERROR] Could not approve mission {args.mission_id} (not found or not in 'planned' status)", file=sys.stderr)
        sys.exit(1)


async def cmd_status(args):
    """Show mission progress."""
    bridge = _get_bridge()
    text = await bridge.status(args.mission_id)
    if text:
        print(text)
    else:
        print(f"[ERROR] Mission {args.mission_id} not found", file=sys.stderr)
        sys.exit(1)


async def cmd_list(args):
    """List all missions."""
    bridge = _get_bridge()
    text = await bridge.list_missions(include_completed=args.include_completed)
    print(text)


async def cmd_cancel(args):
    """Cancel a mission."""
    bridge = _get_bridge()
    ok = await bridge.cancel(args.mission_id)
    if ok:
        print(f"[OK] Mission {args.mission_id} cancelled")
    else:
        print(f"[ERROR] Could not cancel mission {args.mission_id}", file=sys.stderr)
        sys.exit(1)


async def cmd_pause(args):
    """Pause a running mission."""
    bridge = _get_bridge()
    ok = await bridge.pause(args.mission_id)
    if ok:
        print(f"[OK] Mission {args.mission_id} paused")
    else:
        print(f"[ERROR] Could not pause mission {args.mission_id} (not running?)", file=sys.stderr)
        sys.exit(1)


async def cmd_resume(args):
    """Resume a paused mission."""
    bridge = _get_bridge()
    ok = await bridge.resume(args.mission_id)
    if ok:
        print(f"[OK] Mission {args.mission_id} resumed")
    else:
        print(f"[ERROR] Could not resume mission {args.mission_id} (not paused?)", file=sys.stderr)
        sys.exit(1)


async def cmd_log(args):
    """View mission log entries."""
    bridge = _get_bridge()
    entries = bridge.get_log(args.mission_id, tail=args.tail)
    if not entries:
        print(f"No log entries for mission {args.mission_id}")
        return
    print(f"Log for {args.mission_id} ({len(entries)} entries):\n")
    for entry in entries:
        print(f"  {entry}")


# ── Main ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Mission CLI — autonomous goal execution",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            examples:
              # Plan a mission (review before executing)
              %(prog)s plan "Implement JWT auth with refresh tokens" --workspace ~/Projects/api

              # Start immediately (plan + execute)
              %(prog)s start "Add test suite" --workspace ~/Projects/myapp

              # Approve a planned mission
              %(prog)s approve msn-a1b2c3d4

              # Check progress
              %(prog)s status msn-a1b2c3d4

              # List all missions
              %(prog)s list
        """),
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # ─ plan ─
    p_plan = sub.add_parser("plan", help="Decompose goal into milestones/tasks")
    p_plan.add_argument("goal", help="Goal description")
    p_plan.add_argument("--workspace", default=None, help="Working directory")
    p_plan.set_defaults(func=cmd_plan)

    # ─ start ─
    p_start = sub.add_parser("start", help="Plan + auto-approve + start execution")
    p_start.add_argument("goal", help="Goal description")
    p_start.add_argument("--workspace", default=None, help="Working directory")
    p_start.set_defaults(func=cmd_start)

    # ─ approve ─
    p_approve = sub.add_parser("approve", help="Approve a planned mission")
    p_approve.add_argument("mission_id", help="Mission ID (e.g. msn-a1b2c3d4)")
    p_approve.set_defaults(func=cmd_approve)

    # ─ status ─
    p_status = sub.add_parser("status", help="Show mission progress")
    p_status.add_argument("mission_id", help="Mission ID")
    p_status.set_defaults(func=cmd_status)

    # ─ list ─
    p_list = sub.add_parser("list", help="List all missions")
    p_list.add_argument("--include-completed", action="store_true", default=False,
                        help="Include completed/failed/cancelled missions")
    p_list.set_defaults(func=cmd_list)

    # ─ cancel ─
    p_cancel = sub.add_parser("cancel", help="Cancel a mission")
    p_cancel.add_argument("mission_id", help="Mission ID")
    p_cancel.set_defaults(func=cmd_cancel)

    # ─ pause ─
    p_pause = sub.add_parser("pause", help="Pause a running mission")
    p_pause.add_argument("mission_id", help="Mission ID")
    p_pause.set_defaults(func=cmd_pause)

    # ─ resume ─
    p_resume = sub.add_parser("resume", help="Resume a paused mission")
    p_resume.add_argument("mission_id", help="Mission ID")
    p_resume.set_defaults(func=cmd_resume)

    # ─ log ─
    p_log = sub.add_parser("log", help="View mission log entries")
    p_log.add_argument("mission_id", help="Mission ID")
    p_log.add_argument("--tail", type=int, default=None, help="Show only last N entries")
    p_log.set_defaults(func=cmd_log)

    args = parser.parse_args()

    try:
        asyncio.run(args.func(args))
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
