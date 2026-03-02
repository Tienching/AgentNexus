#!/usr/bin/env python3
"""
Task Manager CLI — full CRUD lifecycle for Nexus tasks.

Subcommands:
    plan      Create tasks from a JSON plan (batch, with dependency resolution)
    create    Create a single task
    list      List tasks (compact summary, with filters)
    get       Get task detail
    log       Get task conversation log (with tail/limit to control context)
    result    Get task result (final assistant message only — minimal context)
    continue  Follow up on an existing task (re-enqueue with new message)
    cancel    Cancel a task
    delete    Hard-delete a task
    status    Update task status
    projects  List projects

All output is designed to be compact and context-friendly for LLM agents.
"""
import argparse
import json
import sys
import urllib.request
import urllib.error
import urllib.parse
import os
import textwrap

# ── Config ──────────────────────────────────────────────────────────
API_BASE = os.environ.get("NEXUS_API_URL", "http://localhost:8081/api/nexus")
DEFAULT_EXEC_USER = os.environ.get("EXEC_USER", "ubuntu")

# Maximum chars of task result/log to return (prevent context blowup)
MAX_OUTPUT_CHARS = int(os.environ.get("MAX_OUTPUT_CHARS", "8000"))


# ── Exceptions ──────────────────────────────────────────────────────
class APIError(Exception):
    """Raised when an HTTP request to Nexus API fails."""

    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


# ── HTTP helpers ────────────────────────────────────────────────────
def _request(method: str, path: str, data=None, params=None) -> dict:
    """Make an HTTP request and return parsed JSON response."""
    url = f"{API_BASE}{path}"
    if params:
        qs = urllib.parse.urlencode(
            {k: v for k, v in params.items() if v is not None}
        )
        url = f"{url}?{qs}" if "?" not in url else f"{url}&{qs}"

    body = json.dumps(data).encode("utf-8") if data else None
    headers = {"Content-Type": "application/json"} if data else {}

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise APIError(f"HTTP {e.code}: {err_body}", status_code=e.code)
    except urllib.error.URLError as e:
        raise APIError(f"Connection error: {e}")


def _get(path: str, params=None):
    return _request("GET", path, params=params)


def _post(path: str, data=None, params=None):
    return _request("POST", path, data=data, params=params)


def _patch(path: str, data=None, params=None):
    return _request("PATCH", path, data=data, params=params)


def _delete(path: str, params=None):
    return _request("DELETE", path, params=params)


# ── Formatters (compact, LLM-friendly) ──────────────────────────────
def _format_task_line(t: dict) -> str:
    """One-line task summary: [STATUS] ID  title (provider)."""
    status = t.get("status", "?").upper()
    tid = t.get("id", "?")
    # Prefer title; fall back to first line of description
    desc_raw = t.get("description", "")
    title = desc_raw.split("\n", 1)[0][:80] if desc_raw else "(no description)"
    provider = t.get("provider", "")
    deps = t.get("depends_on", [])
    dep_str = f" deps=[{','.join(deps[:3])}]" if deps else ""
    return f"  [{status:9s}] {tid}  {title}  ({provider}){dep_str}"


def _format_task_detail(t: dict) -> str:
    """Multi-line task detail (still compact)."""
    lines = [
        f"Task: {t.get('id')}",
        f"  Status:   {t.get('status', '?').upper()}",
        f"  Priority: {t.get('priority', '?')}",
        f"  Provider: {t.get('provider', '?')} / {t.get('alias', '?')}",
    ]
    if t.get("workspace"):
        lines.append(f"  Workspace: {t['workspace']}")
    if t.get("project_name") or t.get("project_id"):
        lines.append(f"  Project:  {t.get('project_name', '')} ({t.get('project_id', '')})")
    if t.get("depends_on"):
        lines.append(f"  Depends:  {', '.join(t['depends_on'])}")
    if t.get("error_message"):
        lines.append(f"  Error:    {t['error_message'][:200]}")
    if t.get("session_id"):
        lines.append(f"  Session:  {t['session_id']}")
    lines.append(f"  Desc:     {t.get('description', '')[:300]}")
    ts_fields = ["created_at", "started_at", "completed_at"]
    for f in ts_fields:
        if t.get(f):
            lines.append(f"  {f}: {t[f]}")
    return "\n".join(lines)


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n\n... [truncated, showing {max_chars}/{len(text)} chars]"


# ── Subcommands ─────────────────────────────────────────────────────

def cmd_plan(args):
    """Create tasks from a JSON plan (batch, with dependency resolution)."""
    try:
        plan = json.loads(args.plan)
    except Exception as e:
        print(f"Error parsing JSON: {e}", file=sys.stderr)
        sys.exit(1)

    tasks = plan.get("tasks", [])
    if not tasks:
        print("No tasks in plan.")
        return

    id_map = {}
    print(f"Creating {len(tasks)} tasks...")

    success_count = 0
    for t in tasks:
        # Resolve dependencies
        real_deps = []
        for dep_id in t.get("depends_on", []):
            if dep_id in id_map:
                real_deps.append(id_map[dep_id])
            else:
                print(f"  [WARN] Dep '{dep_id}' for task '{t.get('id')}' not resolved yet")

        title = t.get("title", "Untitled")
        description = t.get("description", "")
        full_desc = f"{title}: {description}" if description else title

        provider = t.get("provider")
        alias = t.get("alias")
        exec_user = t.get("exec_user") or args.exec_user

        payload = {
            "description": full_desc,
            "provider": provider,
            "alias": alias,
            "workspace": t.get("workspace"),
            "project_id": args.project_id,
            "depends_on": real_deps,
            "exec_user": exec_user,
        }
        # Remove None values
        payload = {k: v for k, v in payload.items() if v is not None}

        try:
            result = _post("/tasks", data=payload, params={"exec_user": exec_user})
            real_id = result.get("id")
            if real_id:
                if t.get("id"):
                    id_map[t["id"]] = real_id
                print(f"  [OK] {title[:50]} -> {real_id}")
                success_count += 1
            else:
                print(f"  [FAIL] {title[:50]} -- no ID in response")
        except APIError as e:
            print(f"  [FAIL] {title[:50]} -- {e}")
            continue

    print(f"\nCreated {success_count}/{len(tasks)} tasks.")
    if id_map:
        print("ID map: " + ", ".join(f"{k}->{v}" for k, v in id_map.items()))


def cmd_create(args):
    """Create a single task."""
    payload = {"description": args.description}
    if args.provider:
        payload["provider"] = args.provider
    if args.alias:
        payload["alias"] = args.alias
    if args.workspace:
        payload["workspace"] = args.workspace
    if args.project_id:
        payload["project_id"] = args.project_id
    if args.project_name:
        payload["project_name"] = args.project_name
    if args.depends_on:
        payload["depends_on"] = args.depends_on.split(",")

    result = _post("/tasks", data=payload, params={"exec_user": args.exec_user})
    print(f"[OK] Created task {result.get('id')}")
    print(_format_task_detail(result))


def cmd_list(args):
    """List tasks (compact summary)."""
    params = {
        "exec_user": args.exec_user,
        "page": args.page,
        "page_size": args.page_size,
    }
    if args.status:
        params["status"] = args.status
    if args.project_id:
        params["project_id"] = args.project_id
    if args.search:
        params["search"] = args.search

    result = _get("/tasks", params=params)
    tasks = result.get("tasks", [])
    total = result.get("total", 0)

    print(f"Tasks ({len(tasks)}/{total}, page {result.get('page', 1)}):")
    if not tasks:
        print("  (none)")
    for t in tasks:
        print(_format_task_line(t))

    # Summary by status
    statuses = {}
    for t in tasks:
        s = t.get("status", "?")
        statuses[s] = statuses.get(s, 0) + 1
    if statuses:
        summary = " | ".join(f"{k}:{v}" for k, v in sorted(statuses.items()))
        print(f"\n  Summary: {summary}")


def cmd_get(args):
    """Get task detail."""
    result = _get(f"/tasks/{args.task_id}", params={"exec_user": args.exec_user})
    print(_format_task_detail(result))


def cmd_log(args):
    """Get task conversation log (context-controlled)."""
    params = {"exec_user": args.exec_user}
    # tail and limit are mutually exclusive (API: tail takes priority)
    if args.tail:
        params["tail"] = args.tail
    elif args.limit:
        params["limit"] = args.limit

    result = _get(f"/tasks/{args.task_id}/agui/messages", params=params)
    messages = result.get("messages", [])

    if not messages:
        print(f"No conversation log for task {args.task_id}")
        return

    output_parts = []
    for m in messages:
        role = m.get("role", "?")
        content = m.get("content", "")
        # Compact format: role prefix + content
        prefix = "[user]" if role == "user" else "[assistant]" if role == "assistant" else f"[{role}]"
        output_parts.append(f"{prefix} {content}")

    full_output = "\n\n".join(output_parts)
    max_chars = args.max_chars or MAX_OUTPUT_CHARS
    print(f"Conversation log for task {args.task_id} ({len(messages)} messages):\n")
    print(_truncate(full_output, max_chars))


def cmd_result(args):
    """Get only the final task result (last assistant message).

    This is the most context-efficient way to check what a task produced.
    """
    # Fetch last 20 messages to reliably find the final assistant response
    # (tail=5 may miss it if there are trailing tool_call/tool_result messages)
    params = {"exec_user": args.exec_user, "tail": 20}
    result = _get(f"/tasks/{args.task_id}/agui/messages", params=params)
    messages = result.get("messages", [])

    # Find the last assistant message
    for m in reversed(messages):
        if m.get("role") == "assistant" and m.get("content", "").strip():
            content = m["content"]
            max_chars = args.max_chars or MAX_OUTPUT_CHARS
            print(f"Result for task {args.task_id}:\n")
            print(_truncate(content, max_chars))
            return

    # Also check the task itself for error_message
    task = _get(f"/tasks/{args.task_id}", params={"exec_user": args.exec_user})
    status_val = task.get("status", "?")
    if task.get("error_message"):
        print(f"Task {args.task_id} [{status_val}] error: {task['error_message']}")
    else:
        print(f"Task {args.task_id} [{status_val}] — no result yet")


def cmd_continue(args):
    """Continue chatting on an existing task (follow-up question)."""
    payload = {"message": args.message}
    if args.model:
        payload["model"] = args.model

    result = _post(
        f"/tasks/{args.task_id}/continue",
        data=payload,
        params={"exec_user": args.exec_user},
    )
    print(f"[OK] Enqueued follow-up for task {result.get('id')}")
    print(_format_task_detail(result))


def cmd_cancel(args):
    """Cancel a task (shortcut for `status TASK_ID cancelled`)."""
    args.new_status = "cancelled"
    cmd_status(args)


def cmd_delete(args):
    """Hard-delete a task."""
    _delete(f"/tasks/{args.task_id}", params={"exec_user": args.exec_user})
    print(f"[OK] Deleted task {args.task_id}")


def cmd_status(args):
    """Update task status."""
    result = _patch(
        f"/tasks/{args.task_id}/status",
        data={"status": args.new_status},
        params={"exec_user": args.exec_user},
    )
    print(f"[OK] Task {args.task_id} -> {result.get('status', args.new_status)}")


def cmd_projects(args):
    """List projects."""
    result = _get("/projects", params={"exec_user": args.exec_user})
    # Handle both list and dict (paginated) response formats
    projects = result if isinstance(result, list) else result.get("projects", [])
    if not projects:
        print("No projects found.")
        return
    print("Projects:")
    for p in projects:
        total = p.get("total_tasks", 0)
        pending = p.get("pending", 0) + p.get("todo", 0)
        doing = p.get("in_progress", 0) + p.get("doing", 0)
        done = p.get("completed", 0) + p.get("done", 0)
        print(f"  {p.get('project_id', '?'):20s} {p.get('project_name', ''):30s} [{total} tasks: {pending}P/{doing}D/{done}Done]")


# ── Main ────────────────────────────────────────────────────────────

def main():
    global API_BASE

    parser = argparse.ArgumentParser(
        description="Task Manager CLI for Nexus",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            examples:
              # Create tasks from a plan
              %(prog)s plan --plan '{"tasks": [...]}'

              # List active tasks (compact)
              %(prog)s list --status todo --page-size 10

              # Get task result (minimal context)
              %(prog)s result TASK_ID

              # Check task conversation (last 5 messages)
              %(prog)s log TASK_ID --tail 5

              # Cancel a stuck task
              %(prog)s cancel TASK_ID
        """),
    )
    parser.add_argument("--api", default=API_BASE, help="Nexus API base URL")
    parser.add_argument("--exec-user", default=DEFAULT_EXEC_USER, help="Exec user")

    sub = parser.add_subparsers(dest="command", required=True)

    # ─ plan ─
    p_plan = sub.add_parser("plan", help="Create tasks from a JSON plan")
    p_plan.add_argument("--plan", required=True, help="JSON task plan")
    p_plan.add_argument("--project-id", default=None, help="Project ID")
    p_plan.set_defaults(func=cmd_plan)

    # ─ create ─
    p_create = sub.add_parser("create", help="Create a single task")
    p_create.add_argument("description", help="Task description")
    p_create.add_argument("--provider", default=None)
    p_create.add_argument("--alias", default=None)
    p_create.add_argument("--workspace", default=None)
    p_create.add_argument("--project-id", default=None)
    p_create.add_argument("--project-name", default=None)
    p_create.add_argument("--depends-on", default=None, help="Comma-separated task IDs")
    p_create.set_defaults(func=cmd_create)

    # ─ list ─
    p_list = sub.add_parser("list", help="List tasks (compact)")
    p_list.add_argument("--status", default=None, help="Filter: todo/doing/done/failed/cancelled/archived")
    p_list.add_argument("--project-id", default=None)
    p_list.add_argument("--search", default=None)
    p_list.add_argument("--page", type=int, default=1)
    p_list.add_argument("--page-size", type=int, default=15)
    p_list.set_defaults(func=cmd_list)

    # ─ get ─
    p_get = sub.add_parser("get", help="Get task detail")
    p_get.add_argument("task_id", help="Task ID")
    p_get.set_defaults(func=cmd_get)

    # ─ log ─
    p_log = sub.add_parser("log", help="Get task conversation log")
    p_log.add_argument("task_id", help="Task ID")
    p_log_group = p_log.add_mutually_exclusive_group()
    p_log_group.add_argument("--tail", type=int, default=None, help="Last N messages only (recommended)")
    p_log_group.add_argument("--limit", type=int, default=None, help="First N messages only")
    p_log.add_argument("--max-chars", type=int, default=None, help=f"Max output chars (default {MAX_OUTPUT_CHARS})")
    p_log.set_defaults(func=cmd_log)

    # ─ result ─
    p_result = sub.add_parser("result", help="Get task result (final answer only)")
    p_result.add_argument("task_id", help="Task ID")
    p_result.add_argument("--max-chars", type=int, default=None, help=f"Max output chars (default {MAX_OUTPUT_CHARS})")
    p_result.set_defaults(func=cmd_result)

    # ─ continue ─
    p_continue = sub.add_parser("continue", help="Continue chatting on an existing task")
    p_continue.add_argument("task_id", help="Task ID")
    p_continue.add_argument("message", help="Follow-up message to send")
    p_continue.add_argument("--model", default=None, help="Override model for this run")
    p_continue.set_defaults(func=cmd_continue)

    # ─ cancel ─
    p_cancel = sub.add_parser("cancel", help="Cancel a task")
    p_cancel.add_argument("task_id", help="Task ID")
    p_cancel.set_defaults(func=cmd_cancel)

    # ─ delete ─
    p_del = sub.add_parser("delete", help="Hard-delete a task")
    p_del.add_argument("task_id", help="Task ID")
    p_del.set_defaults(func=cmd_delete)

    # ─ status ─
    p_status = sub.add_parser("status", help="Update task status")
    p_status.add_argument("task_id", help="Task ID")
    p_status.add_argument("new_status", help="New status: todo/doing/done/failed/cancelled")
    p_status.set_defaults(func=cmd_status)

    # ─ projects ─
    p_projects = sub.add_parser("projects", help="List projects")
    p_projects.set_defaults(func=cmd_projects)

    args = parser.parse_args()

    # Override API base if --api is specified
    if args.api != API_BASE:
        API_BASE = args.api

    try:
        args.func(args)
    except APIError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
