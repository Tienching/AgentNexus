# -*- coding: utf-8 -*-
"""Template clone mode for scheduled tasks.

Allows scheduled tasks to be generated from a template, creating
subtasks automatically based on a template pattern.

Usage:
    from src.nanobot.cron.template_tasks import TemplateTaskGenerator

    generator = TemplateTaskGenerator()
    generator.register_template(
        name="daily-report",
        template={"description": "Report for {date}", "priority": "medium"},
        schedule="0 9 * * *",
    )
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from src.runtime.stores.db import get_db


@dataclass
class TaskTemplate:
    """A task template for cloning."""
    id: Optional[int] = None
    name: str = ""
    description_template: str = ""
    data_template: Dict[str, Any] = field(default_factory=dict)
    priority: str = "medium"
    tags: List[str] = field(default_factory=list)
    schedule: str = ""  # Cron expression
    enabled: bool = True
    last_run: Optional[float] = None
    next_run: Optional[float] = None
    created_at: float = field(default_factory=time.time)

    def clone(self, variables: Dict[str, str]) -> Dict[str, Any]:
        """Clone this template with the given variables.

        Args:
            variables: Variable substitutions (e.g., {"date": "2024-01-15"})

        Returns:
            Task data dict with variables substituted
        """
        # Substitute variables in description
        description = self.description_template
        for key, value in variables.items():
            description = description.replace(f"{{{key}}}", value)

        # Merge template data with variables
        data = {**self.data_template, **variables}
        # Remove special keys that shouldn't be in data
        data.pop("__template_name__", None)

        return {
            "description": description,
            "priority": self.priority,
            "tags": self.tags,
            "data": data,
        }


class TemplateTaskGenerator:
    """Manages task templates and generates tasks from them."""

    def __init__(self):
        self._db = get_db()
        self._ensure_table()
        self._cache: Optional[List[TaskTemplate]] = None
        self._cache_time: float = 0
        self._cache_ttl: float = 60.0

    def _ensure_table(self) -> None:
        """Create the task_templates table if it doesn't exist."""
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS task_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description_template TEXT NOT NULL,
                data_template TEXT NOT NULL DEFAULT '{}',
                priority TEXT NOT NULL DEFAULT 'medium',
                tags TEXT NOT NULL DEFAULT '[]',
                schedule TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                last_run REAL,
                next_run REAL,
                created_at REAL NOT NULL
            )
        """)
        self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_template_schedule
            ON task_templates (schedule)
        """)

    def _load_templates(self) -> List[TaskTemplate]:
        """Load templates from database with caching."""
        now = time.time()
        if self._cache and (now - self._cache_time) < self._cache_ttl:
            return self._cache

        self._ensure_table()
        rows = self._db.execute_fetchall("SELECT * FROM task_templates WHERE enabled = 1")
        templates = []
        for row in rows:
            templates.append(
                TaskTemplate(
                    id=row["id"],
                    name=row["name"],
                    description_template=row["description_template"],
                    data_template=json.loads(row["data_template"]) if row["data_template"] else {},
                    priority=row["priority"],
                    tags=json.loads(row["tags"]) if row["tags"] else [],
                    schedule=row["schedule"],
                    enabled=bool(row["enabled"]),
                    last_run=row["last_run"],
                    next_run=row["next_run"],
                    created_at=row["created_at"],
                )
            )
        self._cache = templates
        self._cache_time = now
        return templates

    def register_template(
        self,
        name: str,
        description_template: str,
        data_template: Optional[Dict[str, Any]] = None,
        priority: str = "medium",
        tags: Optional[List[str]] = None,
        schedule: str = "",
    ) -> TaskTemplate:
        """Register a new task template.

        Args:
            name: Unique template name
            description_template: Description with {variable} placeholders
            data_template: Additional data to copy to spawned tasks
            priority: Task priority (low, medium, high)
            tags: Tags to apply to spawned tasks
            schedule: Cron expression for scheduled execution

        Returns:
            The created TaskTemplate
        """
        self._ensure_table()
        now = time.time()

        data_template = data_template or {}
        tags = tags or []

        # Check if template already exists
        existing = self._db.execute_fetchone(
            "SELECT id FROM task_templates WHERE name = ?", (name,)
        )
        if existing:
            self._db.execute(
                """UPDATE task_templates SET
                    description_template = ?, data_template = ?, priority = ?,
                    tags = ?, schedule = ?, enabled = 1
                    WHERE name = ?""",
                (description_template, json.dumps(data_template), priority, json.dumps(tags), schedule, name),
            )
            template_id = existing["id"]
        else:
            cursor = self._db.execute(
                """INSERT INTO task_templates
                    (name, description_template, data_template, priority, tags, schedule, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (name, description_template, json.dumps(data_template), priority, json.dumps(tags), schedule, now),
            )
            template_id = cursor.lastrowid

        self._cache = None

        return TaskTemplate(
            id=template_id,
            name=name,
            description_template=description_template,
            data_template=data_template,
            priority=priority,
            tags=tags,
            schedule=schedule,
            enabled=True,
            created_at=now,
        )

    def unregister_template(self, name: str) -> bool:
        """Disable a template by name.

        Args:
            name: Template name to disable

        Returns:
            True if disabled, False if not found
        """
        self._ensure_table()
        result = self._db.execute(
            "UPDATE task_templates SET enabled = 0 WHERE name = ?",
            (name,),
        )
        self._cache = None
        return result.rowcount > 0

    def get_template(self, name: str) -> Optional[TaskTemplate]:
        """Get a template by name.

        Args:
            name: Template name

        Returns:
            The TaskTemplate if found, None otherwise
        """
        templates = self._load_templates()
        for template in templates:
            if template.name == name:
                return template
        return None

    def generate_task(
        self,
        template_name: str,
        variables: Optional[Dict[str, str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Generate a task from a template.

        Args:
            template_name: Name of the template to use
            variables: Variables to substitute in the template

        Returns:
            Task data dict, or None if template not found
        """
        template = self.get_template(template_name)
        if not template:
            logger.warning(f"Template not found: {template_name}")
            return None

        variables = variables or {}

        # Auto-add common variables
        now = datetime.now(timezone.utc)
        if "date" not in variables:
            variables["date"] = now.strftime("%Y-%m-%d")
        if "time" not in variables:
            variables["time"] = now.strftime("%H:%M")
        if "datetime" not in variables:
            variables["datetime"] = now.isoformat()

        # Clone the template with variables
        return template.clone(variables)

    def get_due_templates(self) -> List[TaskTemplate]:
        """Get templates that are due for execution.

        Returns:
            List of templates with schedule that are due
        """
        templates = self._load_templates()
        now = time.time()
        due = []

        for template in templates:
            if not template.schedule or not template.enabled:
                continue

            # Simple schedule check - if next_run is None or past due
            if template.next_run is None or template.next_run <= now:
                due.append(template)

        return due

    def update_last_run(self, name: str, next_run: Optional[float] = None) -> None:
        """Update the last run time for a template.

        Args:
            name: Template name
            next_run: Optional next run timestamp
        """
        now = time.time()
        self._db.execute(
            "UPDATE task_templates SET last_run = ?, next_run = ? WHERE name = ?",
            (now, next_run, name),
        )
        self._cache = None
