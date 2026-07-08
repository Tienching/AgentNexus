# -*- coding: utf-8 -*-
"""Swarm team coordination infrastructure.

Provides TeamFile shared state, mailbox-based async communication,
idle/shutdown negotiation, task claiming, and cross-agent permission
synchronization for multi-agent teams.
"""

from .team_file import TeamFile, TeamMember
from .mailbox import SwarmMailbox, MailMessage
from .coordination import SwarmCoordinator
from .permission_sync import PermissionSyncService, PermissionRequest, PermissionResponse

__all__ = [
    "TeamFile",
    "TeamMember",
    "SwarmMailbox",
    "MailMessage",
    "SwarmCoordinator",
    "PermissionSyncService",
    "PermissionRequest",
    "PermissionResponse",
]
