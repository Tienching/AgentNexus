# -*- coding: utf-8 -*-
"""Agent template storage and preset loading.

The top-level ``agent/templates`` directory contains editable preset Markdown
files. The database stores runtime-editable copies so the Agents page can tune
prompts, model defaults, tools, behaviour, and memory settings without
rewriting repository files. Presets are insert-only on normal startup; explicit
reset reloads a preset from disk.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from src.runtime.stores.db import Database, get_db

_KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TEMPLATE_DIR = _REPO_ROOT / "agent" / "templates"

_TOOL_KEY_MAP = {
    "base_tools": "baseTools",
    "deferred_tools": "deferredTools",
    "disabled_tools": "disabledTools",
    "baseTools": "baseTools",
    "deferredTools": "deferredTools",
    "disabledTools": "disabledTools",
    "mcp": "mcp",
}

_BUILTIN_PRESETS: dict[str, dict[str, Any]] = {
    "nexus": {
        "name": "nexus",
        "role": "主执行智能体",
        "description": "Agent Nexus 默认主智能体，负责理解目标、执行任务、维护上下文并产出可验证结果。",
        "version": "v1",
        "language": "zh-CN",
        "systemPrompt": "你是 Agent Nexus 的默认主智能体。\n\n工作原则：\n- 先明确目标、约束和可验证的成功标准。\n- 优先做最小必要修改，不做无关重构。\n- 对代码修改保持可追踪：说明假设、执行步骤和验证结果。",
        "avatarUrl": "🤖",
        "modelProvider": "auto",
        "modelName": "anthropic/claude-opus-4-5",
        "temperature": 0.1,
        "topP": 1.0,
        "maxIterations": 40,
        "toolConfig": {
            "baseTools": ["Read", "Edit", "Write", "Glob", "Grep", "Bash", "ToolSearch", "Skill", "Agent"],
            "deferredTools": [],
            "disabledTools": [],
            "mcp": [],
        },
        "surfaces": ["messages", "task-board", "history"],
        "capabilities": ["planning", "coding", "review", "shell", "memory"],
        "triggerMode": "reactive",
        "guardrails": {"maxIterations": 40, "requireApproval": False, "contentFilter": "off"},
    },
    "explorer": {
        "name": "explorer",
        "role": "代码库探索智能体",
        "description": "快速定位文件、符号、调用关系和实现差异，输出可执行的上下文摘要。",
        "version": "v1",
        "language": "zh-CN",
        "systemPrompt": "你是专注代码库探索的智能体。\n\n你的职责：\n- 快速回答在哪里、如何实现、依赖关系是什么。\n- 只做只读分析，除非任务明确要求修改。",
        "avatarUrl": "🔎",
        "modelProvider": "auto",
        "modelName": "anthropic/claude-opus-4-5",
        "temperature": 0.0,
        "topP": 1.0,
        "maxIterations": 20,
        "toolConfig": {
            "baseTools": ["Read", "Glob", "Grep", "ToolSearch"],
            "deferredTools": ["Bash"],
            "disabledTools": [],
            "mcp": [],
        },
        "surfaces": ["messages"],
        "capabilities": ["exploration", "analysis", "read-only"],
        "triggerMode": "reactive",
        "guardrails": {"maxIterations": 20, "requireApproval": False, "contentFilter": "off"},
    },
    "worker": {
        "name": "worker",
        "role": "实现智能体",
        "description": "执行边界清晰的代码修改任务，并负责列出改动文件和验证结果。",
        "version": "v1",
        "language": "zh-CN",
        "systemPrompt": "你是执行实现任务的智能体。\n\n工作方式：\n- 只修改分配给你的范围，不回滚其他人的改动。\n- 先复现或理解问题，再实现最小修复。",
        "avatarUrl": "🛠️",
        "modelProvider": "auto",
        "modelName": "anthropic/claude-opus-4-5",
        "temperature": 0.1,
        "topP": 1.0,
        "maxIterations": 35,
        "toolConfig": {
            "baseTools": ["Read", "Edit", "Write", "Glob", "Grep", "Bash", "ToolSearch"],
            "deferredTools": ["Skill"],
            "disabledTools": [],
            "mcp": [],
        },
        "surfaces": ["messages", "task-board"],
        "capabilities": ["implementation", "testing", "patching"],
        "triggerMode": "reactive",
        "guardrails": {"maxIterations": 35, "requireApproval": False, "contentFilter": "off"},
    },
}

_JSON_FIELD_DEFAULTS: dict[str, Any] = {
    "tool_config_json": {},
    "skill_config_json": {},
    "knowledge_config_json": {},
    "schedule_json": None,
    "event_subscriptions_json": [],
    "surfaces_json": [],
    "capabilities_json": [],
    "guardrails_json": {},
}

_FIELD_TO_COLUMN = {
    "role": "role",
    "description": "description",
    "version": "version",
    "language": "language",
    "systemPrompt": "system_prompt",
    "avatarUrl": "avatar_url",
    "modelProvider": "model_provider",
    "modelName": "model_name",
    "temperature": "temperature",
    "topP": "top_p",
    "maxTokens": "max_tokens",
    "maxIterations": "max_iterations",
    "triggerMode": "trigger_mode",
    "createdBy": "created_by",
}

_JSON_FIELD_TO_COLUMN = {
    "toolConfig": "tool_config_json",
    "skillConfig": "skill_config_json",
    "knowledgeConfig": "knowledge_config_json",
    "schedule": "schedule_json",
    "eventSubscriptions": "event_subscriptions_json",
    "surfaces": "surfaces_json",
    "capabilities": "capabilities_json",
    "guardrails": "guardrails_json",
}


class AgentTemplateError(ValueError):
    """Domain error raised by :class:`AgentTemplateStore`."""

    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(message)


def _parse_scalar(raw: str) -> Any:
    value = raw.strip()
    if value == "":
        return ""
    if value[0:1] in {'"', "'"} and value[-1:] == value[0]:
        return value[1:-1]
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none"}:
        return None
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part.strip()) for part in inner.split(",")]
    if value.startswith("{") and value.endswith("}"):
        inner = value[1:-1].strip()
        if not inner:
            return {}
        out: dict[str, Any] = {}
        for item in inner.split(","):
            if ":" not in item:
                continue
            key, item_value = item.split(":", 1)
            out[key.strip().strip('"\'')] = _parse_scalar(item_value.strip())
        return out
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def _parse_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    text = raw.lstrip("\ufeff")
    if not text.startswith("---\n"):
        return {}, text.strip()
    parts = text.split("\n---\n", 1)
    if len(parts) != 2:
        return {}, text.strip()
    metadata: dict[str, Any] = {}
    for line in parts[0].splitlines()[1:]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        metadata[key.strip()] = _parse_scalar(value)
    return metadata, parts[1].strip()


def _normalize_tool_config(metadata: dict[str, Any]) -> dict[str, Any]:
    raw = dict(metadata.get("toolConfig") or metadata.get("tool_config") or {})
    for source_key, api_key in _TOOL_KEY_MAP.items():
        if source_key in metadata:
            raw[api_key] = metadata[source_key]
        elif source_key in raw and source_key != api_key:
            raw[api_key] = raw.pop(source_key)
    return {key: value for key, value in raw.items() if key in {"baseTools", "deferredTools", "disabledTools", "mcp"}}


def _template_from_markdown(path: Path) -> dict[str, Any]:
    metadata, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
    name = str(metadata.get("name") or path.stem).strip()
    role = str(metadata.get("role") or name).strip()
    return {
        "name": name,
        "role": role,
        "description": str(metadata.get("description") or ""),
        "version": str(metadata.get("version") or "v1"),
        "language": str(metadata.get("language") or "zh-CN"),
        "systemPrompt": body,
        "avatarUrl": metadata.get("avatar_url") or metadata.get("avatarUrl"),
        "modelProvider": metadata.get("model_provider") or metadata.get("modelProvider"),
        "modelName": metadata.get("model_name") or metadata.get("modelName") or metadata.get("model"),
        "temperature": float(metadata.get("temperature", 0.7) or 0.7),
        "topP": float(metadata.get("top_p", metadata.get("topP", 1.0)) or 1.0),
        "maxTokens": metadata.get("max_tokens") or metadata.get("maxTokens"),
        "maxIterations": int(metadata.get("max_iterations", metadata.get("maxIterations", 15)) or 15),
        "toolConfig": _normalize_tool_config(metadata),
        "skillConfig": metadata.get("skill_config") or metadata.get("skillConfig") or {},
        "knowledgeConfig": metadata.get("knowledge_config") or metadata.get("knowledgeConfig") or {},
        "triggerMode": str(metadata.get("trigger_mode") or metadata.get("triggerMode") or "reactive"),
        "schedule": metadata.get("schedule"),
        "eventSubscriptions": metadata.get("event_subscriptions") or metadata.get("eventSubscriptions") or [],
        "surfaces": list(metadata.get("surfaces") or []),
        "capabilities": list(metadata.get("capabilities") or []),
        "guardrails": metadata.get("guardrails") or {},
    }


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads(raw: Any, default: Any) -> Any:
    if raw in (None, ""):
        return default
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return default


def _validate_name(name: str) -> str:
    normalized = (name or "").strip()
    if not _KEBAB_RE.fullmatch(normalized):
        raise AgentTemplateError(
            "AGENT_TEMPLATE_NAME_INVALID",
            "name 必须是 kebab-case 格式，例如 main-agent",
        )
    return normalized


def _coerce_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


class AgentTemplateStore:
    """SQLite-backed configurable agent template registry."""

    def __init__(
        self,
        db: Optional[Database] = None,
        *,
        templates_dir: str | Path | None = None,
        seed_presets: bool = True,
    ) -> None:
        self._db = db or get_db()
        self._templates_dir = Path(templates_dir) if templates_dir is not None else DEFAULT_TEMPLATE_DIR
        if seed_presets:
            self.seed_presets()

    def _load_preset_templates(self) -> list[dict[str, Any]]:
        templates: list[dict[str, Any]] = []
        if self._templates_dir.is_dir():
            for path in sorted(self._templates_dir.glob("*.md")):
                templates.append(_template_from_markdown(path))
        if not templates:
            templates = [dict(item) for item in _BUILTIN_PRESETS.values()]
        return templates

    def _load_preset(self, name: str) -> dict[str, Any] | None:
        normalized = _validate_name(name)
        path = self._templates_dir / f"{normalized}.md"
        if path.exists():
            return _template_from_markdown(path)
        preset = _BUILTIN_PRESETS.get(normalized)
        return dict(preset) if preset else None

    def seed_presets(self) -> int:
        inserted = 0
        for template in self._load_preset_templates():
            name = _validate_name(str(template.get("name") or ""))
            if self.get(name, seed=False) is not None:
                continue
            self._insert(template, source="preset", has_default=True)
            inserted += 1
        return inserted

    def list_templates(self, *, source: str | None = None) -> list[dict[str, Any]]:
        params: tuple[Any, ...] = ()
        where = ""
        if source:
            where = "WHERE source = ?"
            params = (source,)
        rows = self._db.execute_fetchall(
            f"""
            SELECT * FROM agent_templates
            {where}
            ORDER BY CASE WHEN name = 'nexus' THEN 0 WHEN has_default = 1 THEN 1 ELSE 2 END,
                     name COLLATE NOCASE
            """,
            params,
        )
        return [self._row_to_response(row) for row in rows]

    def get(self, name: str, *, seed: bool = True) -> dict[str, Any] | None:
        normalized = _validate_name(name)
        row = self._db.execute_fetchone("SELECT * FROM agent_templates WHERE name = ?", (normalized,))
        if row is None and seed:
            preset = self._load_preset(normalized)
            if preset is not None:
                return self._insert(preset, source="preset", has_default=True)
            return None
        return self._row_to_response(row) if row else None

    def create(self, payload: dict[str, Any], *, created_by: str | None = None) -> dict[str, Any]:
        name = _validate_name(str(payload.get("name") or ""))
        if self.get(name, seed=False) is not None:
            raise AgentTemplateError("AGENT_TEMPLATE_CONFLICT", f"模板已存在: {name}", status_code=409)
        body = dict(payload)
        body["name"] = name
        if created_by and not body.get("createdBy"):
            body["createdBy"] = created_by
        return self._insert(body, source="custom", has_default=False)

    def patch(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = _validate_name(name)
        current = self.get(normalized)
        if current is None:
            raise AgentTemplateError("AGENT_TEMPLATE_NOT_FOUND", f"模板不存在: {normalized}", status_code=404)
        updates = self._payload_to_columns(payload, partial=True)
        if not updates:
            return current
        updates["updated_at"] = time.time()
        assignments = ", ".join(f"{column} = ?" for column in updates)
        params = tuple(updates.values()) + (normalized,)
        with self._db.transaction() as conn:
            conn.execute(f"UPDATE agent_templates SET {assignments} WHERE name = ?", params)
        updated = self.get(normalized, seed=False)
        assert updated is not None
        return updated

    def delete(self, name: str) -> None:
        normalized = _validate_name(name)
        with self._db.transaction() as conn:
            cursor = conn.execute("DELETE FROM agent_templates WHERE name = ?", (normalized,))
        if cursor.rowcount == 0:
            raise AgentTemplateError("AGENT_TEMPLATE_NOT_FOUND", f"模板不存在: {normalized}", status_code=404)

    def reset(self, name: str) -> dict[str, Any]:
        normalized = _validate_name(name)
        preset = self._load_preset(normalized)
        if preset is None:
            raise AgentTemplateError("AGENT_TEMPLATE_DEFAULT_NOT_FOUND", f"未找到预设模板: {normalized}", status_code=404)
        existing = self.get(normalized, seed=False)
        if existing is None:
            return self._insert(preset, source="preset", has_default=True)
        updates = self._payload_to_columns(preset, partial=False)
        updates.update({"source": "preset", "has_default": 1, "updated_at": time.time()})
        assignments = ", ".join(f"{column} = ?" for column in updates)
        with self._db.transaction() as conn:
            conn.execute(f"UPDATE agent_templates SET {assignments} WHERE name = ?", tuple(updates.values()) + (normalized,))
        updated = self.get(normalized, seed=False)
        assert updated is not None
        return updated

    def _insert(self, payload: dict[str, Any], *, source: str, has_default: bool) -> dict[str, Any]:
        name = _validate_name(str(payload.get("name") or ""))
        fields = self._payload_to_columns(payload, partial=False)
        now = time.time()
        row = {
            "id": str(uuid4()),
            "name": name,
            "source": source,
            "has_default": 1 if has_default else 0,
            "created_at": now,
            "updated_at": now,
            **fields,
        }
        columns = list(row.keys())
        placeholders = ", ".join("?" for _ in columns)
        with self._db.transaction() as conn:
            conn.execute(
                f"INSERT INTO agent_templates ({', '.join(columns)}) VALUES ({placeholders})",
                tuple(row[column] for column in columns),
            )
        created = self.get(name, seed=False)
        assert created is not None
        return created

    def _payload_to_columns(self, payload: dict[str, Any], *, partial: bool) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if not partial and not str(payload.get("role") or "").strip():
            raise AgentTemplateError("AGENT_TEMPLATE_INVALID", "role 不能为空")
        if not partial and not str(payload.get("systemPrompt") or "").strip():
            raise AgentTemplateError("AGENT_TEMPLATE_INVALID", "systemPrompt 不能为空")

        for api_field, column in _FIELD_TO_COLUMN.items():
            if api_field not in payload:
                continue
            value = payload[api_field]
            if api_field in {"role", "systemPrompt"} and not partial and not str(value or "").strip():
                raise AgentTemplateError("AGENT_TEMPLATE_INVALID", f"{api_field} 不能为空")
            if api_field in {"temperature", "topP"} and value is not None:
                value = float(value)
            elif api_field in {"maxTokens", "maxIterations"} and value is not None:
                value = int(value)
            data[column] = value

        for api_field, column in _JSON_FIELD_TO_COLUMN.items():
            if api_field not in payload:
                continue
            value = payload[api_field]
            if api_field in {"surfaces", "capabilities", "eventSubscriptions"}:
                value = _coerce_list(value)
            data[column] = _json_dumps(value)

        if not partial:
            defaults = {
                "description": "",
                "version": "v1",
                "language": "zh-CN",
                "avatar_url": None,
                "model_provider": None,
                "model_name": None,
                "temperature": 0.7,
                "top_p": 1.0,
                "max_tokens": None,
                "max_iterations": 15,
                "trigger_mode": "reactive",
                "created_by": payload.get("createdBy"),
            }
            for column, value in defaults.items():
                data.setdefault(column, value)
            for column, default in _JSON_FIELD_DEFAULTS.items():
                if column == "schedule_json" and default is None:
                    data.setdefault(column, None)
                else:
                    data.setdefault(column, _json_dumps(default))
        return data

    @staticmethod
    def _row_to_response(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "role": row["role"],
            "description": row.get("description") or "",
            "version": row.get("version") or "v1",
            "language": row.get("language") or "zh-CN",
            "source": row.get("source") or "custom",
            "hasDefault": bool(row.get("has_default")),
            "systemPrompt": row.get("system_prompt") or "",
            "avatarUrl": row.get("avatar_url"),
            "modelProvider": row.get("model_provider"),
            "modelName": row.get("model_name"),
            "temperature": float(row.get("temperature") if row.get("temperature") is not None else 0.7),
            "topP": float(row.get("top_p") if row.get("top_p") is not None else 1.0),
            "maxTokens": row.get("max_tokens"),
            "maxIterations": int(row.get("max_iterations") if row.get("max_iterations") is not None else 15),
            "toolConfig": _json_loads(row.get("tool_config_json"), {}),
            "skillConfig": _json_loads(row.get("skill_config_json"), {}),
            "knowledgeConfig": _json_loads(row.get("knowledge_config_json"), {}),
            "triggerMode": row.get("trigger_mode") or "reactive",
            "schedule": _json_loads(row.get("schedule_json"), None),
            "eventSubscriptions": _json_loads(row.get("event_subscriptions_json"), []),
            "surfaces": _json_loads(row.get("surfaces_json"), []),
            "capabilities": _json_loads(row.get("capabilities_json"), []),
            "guardrails": _json_loads(row.get("guardrails_json"), {}),
            "createdBy": row.get("created_by"),
            "createdAt": row.get("created_at"),
            "updatedAt": row.get("updated_at"),
        }


_instance: AgentTemplateStore | None = None


def get_agent_template_store() -> AgentTemplateStore:
    global _instance
    if _instance is None:
        _instance = AgentTemplateStore()
    return _instance


def reset_agent_template_store() -> None:
    global _instance
    _instance = None
