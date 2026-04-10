# -*- coding: utf-8 -*-
"""Migration v009: Add security_events and agent_trust_scores tables.

Adds tables for:
- security_events: structured security event logging
- agent_trust_scores: per-agent trust scoring based on security behavior

Version: 9
Name: add_security_tables
"""

from __future__ import annotations

VERSION = 9
NAME = "add_security_tables"


def up(conn) -> None:
    """Create security_events and agent_trust_scores tables."""
    # Security events table - mirrors Mission Control's security_events table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS security_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'info',
            source TEXT,
            agent_name TEXT,
            detail TEXT,
            ip_address TEXT,
            workspace_id INTEGER NOT NULL DEFAULT 1,
            tenant_id INTEGER NOT NULL DEFAULT 1,
            created_at REAL NOT NULL
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_security_events_workspace
        ON security_events (workspace_id)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_security_events_created_at
        ON security_events (created_at DESC)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_security_events_type
        ON security_events (event_type)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_security_events_agent
        ON security_events (agent_name)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_security_events_severity
        ON security_events (severity)
    """)

    # Agent trust scores table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_trust_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_name TEXT NOT NULL,
            workspace_id INTEGER NOT NULL DEFAULT 1,
            trust_score REAL NOT NULL DEFAULT 1.0,
            auth_failures INTEGER NOT NULL DEFAULT 0,
            injection_attempts INTEGER NOT NULL DEFAULT 0,
            rate_limit_hits INTEGER NOT NULL DEFAULT 0,
            secret_exposures INTEGER NOT NULL DEFAULT 0,
            successful_tasks INTEGER NOT NULL DEFAULT 0,
            failed_tasks INTEGER NOT NULL DEFAULT 0,
            last_anomaly_at REAL,
            updated_at REAL NOT NULL,
            UNIQUE(agent_name, workspace_id)
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_agent_trust_workspace
        ON agent_trust_scores (workspace_id)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_agent_trust_score
        ON agent_trust_scores (trust_score)
    """)