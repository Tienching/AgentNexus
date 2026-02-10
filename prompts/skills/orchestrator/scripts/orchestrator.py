#!/usr/bin/env python3
"""
Orchestrator Script - Creates tasks from a JSON plan via Nexus API.

Supports:
- Task dependencies (depends_on)
- Per-task provider, agent, and alias specification
- Project grouping via project_id
- Workspace specification per task
"""
import argparse
import json
import sys
import urllib.request
import urllib.error
import os

# Default API URL, can be overridden by env var or arg
API_URL = os.environ.get("NEXUS_API_URL", "http://localhost:8081/api/nexus/tasks")
DEFAULT_EXEC_USER = os.environ.get("EXEC_USER", "ubuntu")

def main():
    parser = argparse.ArgumentParser(description="Create tasks from a JSON plan via Nexus API")
    parser.add_argument("--plan", required=True, help="JSON string of the task plan")
    parser.add_argument("--api", default=API_URL, help="Task API URL")
    parser.add_argument("--project-id", default=None, help="Project ID to group tasks (e.g., session_id)")
    parser.add_argument("--exec-user", default=DEFAULT_EXEC_USER, help="Default exec user for tasks")
    args = parser.parse_args()

    try:
        plan = json.loads(args.plan)
    except Exception as e:
        print(f"Error parsing JSON: {e}")
        sys.exit(1)

    tasks = plan.get("tasks", [])
    if not tasks:
        print("No tasks found in plan.")
        return

    id_map = {} # Maps plan_id -> real_task_id

    print(f"Orchestrating {len(tasks)} tasks via {args.api}...")
    print(f"Default exec_user: {args.exec_user}")
    if args.project_id:
        print(f"Project ID: {args.project_id}")

    # Iterate through tasks.
    # Note: Assumes agent provides topologically sorted list or simple order.

    success_count = 0

    for t in tasks:
        # Resolve dependencies
        real_deps = []
        for dep_id in t.get("depends_on", []):
            if dep_id in id_map:
                real_deps.append(id_map[dep_id])
            else:
                print(f"Warning: Dependency {dep_id} for task {t.get('id')} not found/created yet.")

        # Prepare payload
        title = t.get("title", "Untitled Task")
        description = t.get("description", "")
        # Combine title and description for the legacy description field if needed
        full_description = f"{title}: {description}" if description else title

        # Use workspace from task if provided (must be a valid directory path)
        # If not provided, use None to let executor use default workspace
        workspace = t.get("workspace")  # Can be None
        
        # Get provider, alias, and exec_user from task, with defaults
        provider = t.get("provider")  # None means use system default
        alias = t.get("alias")
        exec_user = t.get("exec_user") or args.exec_user  # Use task exec_user or default

        # Build API URL with exec_user query parameter
        api_url = args.api
        if "?" in api_url:
            api_url = f"{api_url}&exec_user={exec_user}"
        else:
            api_url = f"{api_url}?exec_user={exec_user}"

        payload = {
            "description": full_description,
            "priority": t.get("priority", "thought"),
            "depends_on": real_deps,
            "workspace": workspace,
            "project_id": args.project_id,
            "provider": provider,
            "alias": alias,
            "context": {
                "orchestrator_temp_id": t.get("id"),
                "orchestrator_title": title,
            }
        }

        # Log task details
        provider_info = f" [provider={provider}]" if provider else ""
        alias_info = f" [alias={alias}]" if alias else ""
        user_info = f" [exec_user={exec_user}]"
        print(f"\nCreating: {title}{provider_info}{alias_info}{user_info}")

        # Send Request
        try:
            req = urllib.request.Request(
                api_url,
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )
            with urllib.request.urlopen(req) as res:
                if 200 <= res.status < 300:
                    response_body = res.read().decode('utf-8')
                    response = json.loads(response_body)

                    # Try to find ID in various common fields
                    real_id = response.get("id") or response.get("task_id")

                    if real_id:
                        if t.get("id"):
                            id_map[t.get("id")] = real_id
                        print(f"  [OK] Created -> ID: {real_id}")
                        success_count += 1
                    else:
                        print(f"  [WARN] Created task but could not find ID in response: {response}")
                else:
                     print(f"  [ERR] API returned status {res.status}")

        except urllib.error.URLError as e:
            print(f"  [ERR] Failed to create task '{title}': {e}")
            # We continue trying other tasks even if one fails, though dependent tasks will lack dependencies
        except Exception as e:
            print(f"  [ERR] Unexpected error creating task '{title}': {e}")

    print(f"\n{'='*50}")
    print(f"Orchestration complete. Created {success_count}/{len(tasks)} tasks.")
    
    if id_map:
        print("\nTask ID mapping:")
        for temp_id, real_id in id_map.items():
            print(f"  {temp_id} -> {real_id}")

if __name__ == "__main__":
    main()
