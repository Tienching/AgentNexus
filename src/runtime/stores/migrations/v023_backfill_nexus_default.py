# -*- coding: utf-8 -*-
"""Migration v023: backfill legacy nexus/nanobot defaults to claude.

Earlier task/run rows and v005 schema defaulted new rows to the removed
'nexus'/'nanobot' providers. After the daemon-platform refactor those providers
no longer exist (dispatch falls through to claude via normalize_provider), so
the stored 'nexus' value was a lie about which provider ran. This migration
rewrites historical rows to the truthful 'claude' default and drops the schema
DEFAULT from 'nexus' to 'claude' for the runs table.

Version: 23
Name: backfill_nexus_default
"""

VERSION = 23
NAME = "backfill_nexus_default"


def up(conn) -> None:
    cur = conn.cursor()
    # tasks: provider column
    tcols = {row[1] for row in cur.execute("PRAGMA table_info(tasks)").fetchall()}
    if "provider" in tcols:
        cur.execute("UPDATE tasks SET provider = 'claude' WHERE provider IN ('nexus', 'nanobot')")
    # runs: runtime column
    rcols = {row[1] for row in cur.execute("PRAGMA table_info(runs)").fetchall()} \
        if "runs" in {r[0] for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()} else set()
    if "runtime" in rcols:
        cur.execute("UPDATE runs SET runtime = 'claude' WHERE runtime IN ('nexus', 'nanobot')")
