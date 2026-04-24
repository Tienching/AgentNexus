# -*- coding: utf-8 -*-
"""Server services.

This package intentionally avoids eager imports to prevent circular-import
chains between slash-command modules, service factories, and API-layer
helpers. Public attributes are resolved lazily on first access.
"""

from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "AppServiceContainer": ("src.server.services.app_container", "AppServiceContainer"),
    "get_app_container": ("src.server.services.app_container", "get_app_container"),
    "reset_app_container": ("src.server.services.app_container", "reset_app_container"),
    "CLIExecutor": ("src.server.services.cli_executor", "CLIExecutor"),
    "StreamHandler": ("src.server.services.stream_handler", "StreamHandler"),
    "UserDirectoryManager": ("src.server.services.user_directory", "UserDirectoryManager"),
    "CallbackHandler": ("src.server.services.callback_handler", "CallbackHandler"),
    "RedisClient": ("src.server.services.redis_client", "RedisClient"),
    "get_redis_client": ("src.server.services.redis_client", "get_redis_client"),
    "SessionStorage": ("src.server.services.session_storage", "SessionStorage"),
    "get_session_storage": ("src.server.services.session_storage", "get_session_storage"),
    "HistoryService": ("src.server.services.history_service", "HistoryService"),
    "ControlPlaneService": ("src.server.services.control_plane", "ControlPlaneService"),
    "get_control_plane_service": ("src.server.services.control_plane", "get_control_plane_service"),
    "CollaborationService": ("src.server.services.collaboration_service", "CollaborationService"),
    "ExtensionRegistryService": ("src.server.services.extension_registry", "ExtensionRegistryService"),
    "get_history_service": ("src.server.services.history_service", "get_history_service"),
    "StreamArchiver": ("src.server.services.stream_archiver", "StreamArchiver"),
    "create_archiver": ("src.server.services.stream_archiver", "create_archiver"),
    "TaskQueue": ("src.server.services.task_storage", "TaskQueue"),
    "get_task_queue": ("src.server.services.task_storage", "get_task_queue"),
    "RuntimeStatus": ("src.server.services.agent_runtimes", "RuntimeStatus"),
    "RuntimeDaemon": ("src.server.services.agent_runtimes", "RuntimeDaemon"),
    "RuntimeDaemonRegistry": ("src.server.services.agent_runtimes", "RuntimeDaemonRegistry"),
    "get_runtime_daemon_registry": ("src.server.services.agent_runtimes", "get_runtime_daemon_registry"),
    "detect_runtime": ("src.server.services.agent_runtimes", "detect_runtime"),
    "detect_all_runtimes": ("src.server.services.agent_runtimes", "detect_all_runtimes"),
    "record_domain_event": ("src.server.services.domain_events", "record_domain_event"),
    "query_domain_events": ("src.server.services.domain_events", "query_domain_events"),
    "count_domain_events": ("src.server.services.domain_events", "count_domain_events"),
    "DomainEvent": ("src.server.services.domain_events", "DomainEvent"),
    "EventBus": ("src.server.services.event_bus", "EventBus"),
    "EventEnvelope": ("src.server.services.event_bus", "EventEnvelope"),
    "get_event_bus": ("src.server.services.event_bus", "get_event_bus"),
    "BareRepoCacheRecord": ("src.server.services.worktree_registry", "BareRepoCacheRecord"),
    "RepoWorktreeRecord": ("src.server.services.worktree_registry", "RepoWorktreeRecord"),
    "RepoWorktreeRegistry": ("src.server.services.worktree_registry", "RepoWorktreeRegistry"),
    "get_repo_worktree_registry": ("src.server.services.worktree_registry", "get_repo_worktree_registry"),
    "WorktreeError": ("src.runtime.commands.slash.worktree", "WorktreeError"),
    "NotGitRepoError": ("src.runtime.commands.slash.worktree", "NotGitRepoError"),
    "WorktreeDirConflictError": ("src.runtime.commands.slash.worktree", "WorktreeDirConflictError"),
    "WorktreeCommandError": ("src.runtime.commands.slash.worktree", "WorktreeCommandError"),
    "WorktreeResult": ("src.runtime.commands.slash.worktree", "WorktreeResult"),
    "ensure_task_worktree": ("src.runtime.commands.slash.worktree", "ensure_task_worktree"),
    "SlashCommandHandler": ("src.runtime.commands.slash.handler", "SlashCommandHandler"),
    "SLASH_COMMANDS": ("src.runtime.commands.slash.handler", "SLASH_COMMANDS"),
    "SlashCommandParseError": ("src.runtime.commands.slash.parser", "SlashCommandParseError"),
    "parse_slash_command": ("src.runtime.commands.slash.parser", "parse_slash_command"),
    "usage_for": ("src.runtime.commands.slash.parser", "usage_for"),
    "TaskExecutor": ("src.runtime.execution.task_executor", "TaskExecutor"),
    "ExecutorState": ("src.runtime.execution.task_executor", "ExecutorState"),
    "TaskHandler": ("src.runtime.execution.task_executor", "TaskHandler"),
    "get_executor": ("src.runtime.execution.task_executor", "get_executor"),
    "set_executor": ("src.runtime.execution.task_executor", "set_executor"),
    "create_and_start_executor": ("src.runtime.execution.task_executor", "create_and_start_executor"),
    "WorkspaceQueueManager": ("src.runtime.execution.workspace_queue", "WorkspaceQueueManager"),
    "TaskScheduler": ("src.runtime.execution.scheduler", "TaskScheduler"),
    "SchedulerState": ("src.runtime.execution.scheduler", "SchedulerState"),
    "get_scheduler": ("src.runtime.execution.scheduler", "get_scheduler"),
    "set_scheduler": ("src.runtime.execution.scheduler", "set_scheduler"),
    "create_and_start_scheduler": ("src.runtime.execution.scheduler", "create_and_start_scheduler"),
    "ScheduleStorage": ("src.server.services.schedule_storage", "ScheduleStorage"),
    "NotificationTarget": ("src.server.services.notification", "NotificationTarget"),
    "NotificationResult": ("src.server.services.notification", "NotificationResult"),
    "NotificationSink": ("src.server.services.notification", "NotificationSink"),
    "UnifiedNotificationHandler": ("src.server.services.notification", "UnifiedNotificationHandler"),
    "get_notification_handler": ("src.server.services.notification", "get_notification_handler"),
    "DiscordSink": ("src.server.services.notification", "DiscordSink"),
    "FeishuSink": ("src.server.services.notification", "FeishuSink"),
    "SlackSink": ("src.server.services.notification", "SlackSink"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
