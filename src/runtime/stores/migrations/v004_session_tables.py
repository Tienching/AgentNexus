# -*- coding: utf-8 -*-
"""Migration v004: Session tables.

Replaces the Redis structure:
  session:{id}:meta                → sessions row
  sessions:all                     → index via updated_at
  user:{name}:sessions             → index via username
  session:{id}:messages            → session_messages rows
  session:{id}:toolcalls           → session_tool_calls rows
  session:{id}:events              → session_events rows
  session:{id}:msg:{mid}:content   → session_streaming_content (with TTL)
  history:hidden                   → history_hidden (in v001)
  historymap:{prov}:{sid}:{hash}  → history_mappings
"""

import sqlite3

VERSION = 4
NAME = "session_tables"


def up(conn: sqlite3.Connection) -> None:
    # ── Session metadata ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id                TEXT PRIMARY KEY,
            thread_id         TEXT,
            title             TEXT,
            username          TEXT,
            agent_name        TEXT,
            workspace         TEXT,
            exec_dir          TEXT,
            exec_dir_override TEXT,
            status            TEXT DEFAULT 'active',
            message_count     INTEGER DEFAULT 0,
            provider          TEXT,
            model             TEXT,
            cli_session_id    TEXT,
            claude_session_id TEXT,
            session_exec_user TEXT,
            exec_user_switched INTEGER DEFAULT 0,
            session_cleared   INTEGER DEFAULT 0,
            target_session_id TEXT,
            workspace_provider TEXT,
            workspace_alias   TEXT,
            handoff_context    TEXT,
            handoff_target_provider TEXT,
            handoff_model      TEXT,
            handoff_pending_summary TEXT,
            handoff_pending_context_mode TEXT DEFAULT 'full',
            handoff_provider  TEXT,
            handoff_alias     TEXT,
            model_override    TEXT,
            active_model      TEXT,
            persistent_mode   INTEGER DEFAULT 0,
            inherited_from    TEXT,
            history_bootstrap_context TEXT,
            created_at        REAL,
            updated_at        REAL,
            expires_at        REAL
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sessions_username
        ON sessions(username, updated_at DESC)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sessions_updated
        ON sessions(updated_at DESC)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sessions_expires
        ON sessions(expires_at)
        WHERE expires_at IS NOT NULL
    """)

    # ── Session messages ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL,
            msg_id      TEXT,
            role        TEXT,
            content     TEXT,
            msg_json    TEXT,
            created_at  REAL,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_session_messages_sid
        ON session_messages(session_id, id)
    """)

    # ── Session tool calls ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_tool_calls (
            call_id     TEXT NOT NULL,
            session_id  TEXT NOT NULL,
            tool_json   TEXT,
            PRIMARY KEY (session_id, call_id),
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    """)

    # ── Session AGUI events ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL,
            event_json  TEXT NOT NULL,
            created_at  REAL,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_session_events_sid
        ON session_events(session_id, id)
    """)

    # ── Streaming content (short TTL) ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_streaming_content (
            session_id  TEXT NOT NULL,
            message_id  TEXT NOT NULL,
            content     TEXT,
            expires_at  REAL,
            PRIMARY KEY (session_id, message_id)
        )
    """)

    # ── History runtime mappings ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS history_mappings (
            provider           TEXT NOT NULL,
            history_session_id TEXT NOT NULL,
            project_hash       TEXT NOT NULL,
            runtime_session_id TEXT NOT NULL,
            expires_at         REAL,
            PRIMARY KEY (provider, history_session_id, project_hash)
        )
    """)
