#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Resource-oriented operator CLI with stable JSON output."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from src.server.services.collaboration_service import CollaborationService
from src.server.services.control_plane import get_control_plane_service
from src.server.services.extension_registry import ExtensionRegistryService
from src.server.services.worktree_registry import get_repo_worktree_registry


def _normalize_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ", ".join(_normalize_scalar(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _json_dump(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _table_dump(payload: Any) -> None:
    if isinstance(payload, list):
        rows = [item if isinstance(item, dict) else {"value": item} for item in payload]
        if not rows:
            print("(empty)")
            return
        columns: list[str] = []
        seen = set()
        for row in rows:
            for key in row.keys():
                if key not in seen:
                    columns.append(key)
                    seen.add(key)
        widths = {
            col: max(len(col), *(len(_normalize_scalar(row.get(col))) for row in rows))
            for col in columns
        }
        header = " | ".join(col.ljust(widths[col]) for col in columns)
        divider = "-+-".join("-" * widths[col] for col in columns)
        print(header)
        print(divider)
        for row in rows:
            print(" | ".join(_normalize_scalar(row.get(col)).ljust(widths[col]) for col in columns))
        return
    if isinstance(payload, dict):
        scalar_items = {k: v for k, v in payload.items() if not isinstance(v, (list, dict))}
        nested_items = {k: v for k, v in payload.items() if isinstance(v, (list, dict))}
        if scalar_items:
            width = max(len(k) for k in scalar_items)
            for key, value in scalar_items.items():
                print(f"{key.ljust(width)} : {_normalize_scalar(value)}")
        for key, value in nested_items.items():
            if scalar_items or key != next(iter(nested_items)):
                print()
            print(f"[{key}]")
            _table_dump(value)
        if not payload:
            print("(empty)")
        return
    print(_normalize_scalar(payload))


def _emit(payload: Any, fmt: str) -> None:
    if fmt == 'table':
        _table_dump(payload)
        return
    _json_dump(payload)


def _dashboard_payload() -> dict[str, Any]:
    control_plane = get_control_plane_service()
    tenants = [item.to_dict() for item in control_plane.list_tenants()]
    workspaces = [item.to_dict() for item in control_plane.list_workspaces()]

    collab = CollaborationService(exec_user='default')
    projects = [item.to_dict() for item in collab.list_projects()]
    issues = [item.to_dict() for item in collab.list_issues()]
    inbox = collab.get_inbox().to_dict()

    extensions = ExtensionRegistryService(exec_user=None)
    providers = [item.to_dict() for item in extensions.list_providers()]
    plugins = [item.to_dict() for item in extensions.list_plugins()]
    panels = [item.to_dict() for item in extensions.list_panels()]

    registry = get_repo_worktree_registry()
    repos = [item.to_dict() for item in registry.list_records()]
    caches = [item.to_dict() for item in registry.list_caches()]

    return {
        'summary': {
            'tenants': len(tenants),
            'workspaces': len(workspaces),
            'projects': len(projects),
            'issues': len(issues),
            'inbox_tasks': inbox.get('total_tasks', 0),
            'providers': len(providers),
            'plugins': len(plugins),
            'panels': len(panels),
            'repos': len(repos),
            'repo_caches': len(caches),
        },
        'tenants': tenants,
        'workspaces': workspaces,
        'projects': projects,
        'issues': issues,
        'providers': providers,
        'plugins': plugins,
        'panels': panels,
        'repos': repos,
        'repo_caches': caches,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='nexusctl', description='Agent Nexus operator CLI')
    parser.add_argument('--format', choices=('json', 'table'), default='json', help='Output format')
    sub = parser.add_subparsers(dest='resource')

    dashboard = sub.add_parser('dashboard', help='Show an operator dashboard across major resources')
    dashboard.add_argument('--include-details', action='store_true', help='Include full resource collections')

    cp = sub.add_parser('control-plane', help='tenant / workspace control-plane')
    cp_sub = cp.add_subparsers(dest='command')
    cp_sub.add_parser('tenants', help='List tenants')
    ws = cp_sub.add_parser('workspaces', help='List workspaces')
    ws.add_argument('--tenant-id')
    access = cp_sub.add_parser('access', help='Resolve workspace access')
    access.add_argument('--username', required=True)
    access.add_argument('--workspace-id', required=True)
    audit = cp_sub.add_parser('audit', help='List workspace audit events')
    audit.add_argument('--workspace-id', required=True)

    collab = sub.add_parser('collab', help='project / issue / inbox collaboration')
    collab_sub = collab.add_subparsers(dest='command')
    collab_sub.add_parser('projects', help='List collaboration projects')
    issues = collab_sub.add_parser('issues', help='List collaboration issues')
    issues.add_argument('--project-id')
    issues.add_argument('--inbox-only', action='store_true')
    inbox = collab_sub.add_parser('inbox', help='Show collaboration inbox')
    inbox.add_argument('--exec-user', default='default')
    projects = collab_sub.add_parser('projects-user', help='List collaboration projects by exec user')
    projects.add_argument('--exec-user', default='default')

    ext = sub.add_parser('extensions', help='extension catalog')
    ext_sub = ext.add_subparsers(dest='command')
    ext_cat = ext_sub.add_parser('catalog', help='Show extension catalog')
    ext_cat.add_argument('--exec-user', default=None)

    repos = sub.add_parser('repos', help='repo registry and caches')
    repos_sub = repos.add_subparsers(dest='command')
    repos_sub.add_parser('registry', help='List registered repos')
    repos_sub.add_parser('caches', help='List bare repo caches')
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.resource == 'dashboard':
            payload = _dashboard_payload()
            if not args.include_details:
                payload = {'summary': payload['summary']}
            _emit(payload, args.format)
            return 0
        if args.resource == 'control-plane':
            service = get_control_plane_service()
            if args.command == 'tenants':
                _emit([item.to_dict() for item in service.list_tenants()], args.format)
                return 0
            if args.command == 'workspaces':
                _emit([item.to_dict() for item in service.list_workspaces(tenant_id=args.tenant_id)], args.format)
                return 0
            if args.command == 'access':
                _emit(service.resolve_access(username=args.username, workspace_id=args.workspace_id).to_dict(), args.format)
                return 0
            if args.command == 'audit':
                _emit([item.to_dict() for item in service.list_workspace_audit(workspace_id=args.workspace_id)], args.format)
                return 0
        elif args.resource == 'collab':
            exec_user = getattr(args, 'exec_user', None) or 'default'
            service = CollaborationService(exec_user=exec_user)
            if args.command == 'projects':
                _emit([item.to_dict() for item in service.list_projects()], args.format)
                return 0
            if args.command == 'projects-user':
                _emit([item.to_dict() for item in service.list_projects()], args.format)
                return 0
            if args.command == 'issues':
                _emit([item.to_dict() for item in service.list_issues(project_id=args.project_id, only_inbox=args.inbox_only)], args.format)
                return 0
            if args.command == 'inbox':
                _emit(service.get_inbox().to_dict(), args.format)
                return 0
        elif args.resource == 'extensions':
            if args.command == 'catalog':
                service = ExtensionRegistryService(exec_user=args.exec_user)
                _emit({
                    'providers': [item.to_dict() for item in service.list_providers()],
                    'plugins': [item.to_dict() for item in service.list_plugins()],
                    'bundled_skills': [item.to_dict() for item in service.list_bundled_skills()],
                    'panels': [item.to_dict() for item in service.list_panels()],
                }, args.format)
                return 0
        elif args.resource == 'repos':
            registry = get_repo_worktree_registry()
            if args.command == 'registry':
                _emit([item.to_dict() for item in registry.list_records()], args.format)
                return 0
            if args.command == 'caches':
                _emit([item.to_dict() for item in registry.list_caches()], args.format)
                return 0
    except Exception as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    parser.print_help()
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
