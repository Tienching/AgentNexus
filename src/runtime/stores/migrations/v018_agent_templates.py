# -*- coding: utf-8 -*-
"""Migration v018: configurable agent templates."""

from __future__ import annotations

import sqlite3

VERSION = 18
NAME = "agent_templates"


def up(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_templates (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            role TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            version TEXT NOT NULL DEFAULT 'v1',
            language TEXT NOT NULL DEFAULT 'zh-CN',
            source TEXT NOT NULL DEFAULT 'preset',
            has_default INTEGER NOT NULL DEFAULT 0,
            system_prompt TEXT NOT NULL,
            avatar_url TEXT,
            model_provider TEXT,
            model_name TEXT,
            temperature REAL NOT NULL DEFAULT 0.7,
            top_p REAL NOT NULL DEFAULT 1.0,
            max_tokens INTEGER,
            max_iterations INTEGER NOT NULL DEFAULT 15,
            tool_config_json TEXT NOT NULL DEFAULT '{}',
            skill_config_json TEXT NOT NULL DEFAULT '{}',
            knowledge_config_json TEXT NOT NULL DEFAULT '{}',
            trigger_mode TEXT NOT NULL DEFAULT 'reactive',
            schedule_json TEXT,
            event_subscriptions_json TEXT NOT NULL DEFAULT '[]',
            surfaces_json TEXT NOT NULL DEFAULT '[]',
            capabilities_json TEXT NOT NULL DEFAULT '[]',
            guardrails_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_agent_templates_source
        ON agent_templates(source, name)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_agent_templates_updated_at
        ON agent_templates(updated_at DESC)
    """)


def down(conn: sqlite3.Connection) -> None:
    conn.execute("DROP INDEX IF EXISTS idx_agent_templates_updated_at")
    conn.execute("DROP INDEX IF EXISTS idx_agent_templates_source")
    conn.execute("DROP TABLE IF EXISTS agent_templates")
