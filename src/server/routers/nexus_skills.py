# -*- coding: utf-8 -*-
"""Nexus Skills API Router

Provides REST API endpoints for skills management:
- Discover skills across provider directories
- Create new skills
- Delete existing skills
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from pathlib import Path
from typing import Optional, List, Dict

from fastapi import APIRouter, Depends, HTTPException, Query

from ..config import settings
from ..logger import get_logger
from .nexus_auth import verify_nexus_auth
from .nexus_models import (
    SuccessResponse,
    SkillInfo,
    SkillsResponse,
    CreateSkillRequest,
)

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/nexus",
    tags=["nexus-skills"],
    dependencies=[Depends(verify_nexus_auth)],
)


# ============ Skills Constants ============

# Default provider -> config directory name mapping
_PROVIDER_CONFIG_DIRS = {
    "claude": ".claude",
    "codebuddy": ".codebuddy",
    "codex": ".codex",
    "gemini": ".gemini",
}

# Known providers that have standard skills directories
_KNOWN_PROVIDERS = set(_PROVIDER_CONFIG_DIRS.keys())

# Valid skill name pattern (prevent path injection)
_SKILL_NAME_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]*$')


# ============ Skills Helpers ============


def _parse_skill_md(file_path: Path) -> dict:
    """Parse SKILL.md frontmatter (name, description, version) using regex."""
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}

    # Match YAML frontmatter between --- delimiters
    fm_match = re.match(r'^---\s*\n(.*?)\n---', text, re.DOTALL)
    if not fm_match:
        return {}

    result = {}
    for line in fm_match.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        # Simple key: value parsing (handles quoted and unquoted values)
        m = re.match(r'^(\w+)\s*:\s*"?([^"]*)"?\s*$', line)
        if m:
            result[m.group(1)] = m.group(2).strip()
    return result


def _scan_skills_dir(skills_dir: Path, provider: str) -> List[SkillInfo]:
    """Scan a skills directory and return list of SkillInfo."""
    skills = []
    if not skills_dir.is_dir():
        return skills

    for entry in sorted(skills_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith('.') or entry.name == 'learned':
            continue
        skill_md = entry / "SKILL.md"
        if skill_md.is_file():
            meta = _parse_skill_md(skill_md)
            skills.append(SkillInfo(
                name=meta.get("name", entry.name),
                description=meta.get("description", ""),
                version=meta.get("version", ""),
                provider=provider,
                path=str(entry),
            ))
    return skills


# ============ Skills Endpoints ============


@router.get("/skills", response_model=SkillsResponse)
async def get_skills(
    exec_user: str = Query(default="", description="Exec user for home directory resolution"),
    custom_paths: str = Query(default="", description="JSON-encoded dict of alias->skills_path"),
):
    """Scan provider skills directories and return discovered skills."""
    user = exec_user or settings.exec_user or "ubuntu"
    home_base = settings.user_home_base or "/home"
    user_home = Path(home_base) / user

    # Parse custom alias paths
    alias_paths: Dict[str, str] = {}
    if custom_paths:
        try:
            alias_paths = json.loads(custom_paths)
        except (json.JSONDecodeError, TypeError):
            pass

    result: Dict[str, List[SkillInfo]] = {}

    def _resolve_tilde(path_str: str) -> Path:
        """Resolve ~ or ~/ to the target user home directory."""
        if path_str.startswith("~/") or path_str == "~":
            return user_home / path_str[2:] if len(path_str) > 2 else user_home
        return Path(path_str)

    def _scan_all():
        # Scan default providers
        for provider, config_dir in _PROVIDER_CONFIG_DIRS.items():
            skills_dir = user_home / config_dir / "skills"
            result[provider] = _scan_skills_dir(skills_dir, provider)

        # Scan custom alias paths
        for alias_name, path_str in alias_paths.items():
            if alias_name in _KNOWN_PROVIDERS:
                continue  # Skip if it's a known provider (already scanned)
            skills_dir = _resolve_tilde(path_str)
            if skills_dir.is_absolute():
                result[alias_name] = _scan_skills_dir(skills_dir, alias_name)
            else:
                logger.warning(f"Skipping non-absolute skills path for alias '{alias_name}': {path_str}")

    await asyncio.to_thread(_scan_all)
    return SkillsResponse(providers=result)


@router.post("/skills", response_model=SuccessResponse)
async def create_skill(request: CreateSkillRequest):
    """Create a new skill in the provider's skills directory."""
    provider = (request.provider or "").strip().lower()
    skill_name = (request.skill_name or "").strip()

    if not provider:
        raise HTTPException(status_code=400, detail="provider is required")
    if not skill_name:
        raise HTTPException(status_code=400, detail="skill_name is required")
    if not _SKILL_NAME_RE.match(skill_name):
        raise HTTPException(
            status_code=400,
            detail="Invalid skill name. Only letters, numbers, hyphens, dots, and underscores are allowed.",
        )

    # Determine skills directory
    user = settings.exec_user or "ubuntu"
    home_base = settings.user_home_base or "/home"
    user_home = Path(home_base) / user

    if request.skills_path:
        raw = request.skills_path
        if raw.startswith("~/") or raw == "~":
            skills_dir = user_home / raw[2:] if len(raw) > 2 else user_home
        else:
            skills_dir = Path(raw)
        if not skills_dir.is_absolute():
            raise HTTPException(status_code=400, detail="skills_path must be an absolute path")
    elif provider in _PROVIDER_CONFIG_DIRS:
        skills_dir = user_home / _PROVIDER_CONFIG_DIRS[provider] / "skills"
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider '{provider}'. Provide skills_path for custom aliases.",
        )

    skill_dir = (skills_dir / skill_name).resolve()
    if not str(skill_dir).startswith(str(skills_dir.resolve())):
        raise HTTPException(status_code=400, detail="Invalid skill path")

    def _create():
        if skill_dir.exists():
            raise FileExistsError(f"Skill '{skill_name}' already exists at {skill_dir}")
        skill_dir.mkdir(parents=True, exist_ok=False)
        # Build SKILL.md
        frontmatter = f"---\nname: {skill_name}\ndescription: {request.description}\n---\n\n"
        body = request.content or f"# {skill_name}\n"
        (skill_dir / "SKILL.md").write_text(frontmatter + body, encoding="utf-8")

    try:
        await asyncio.to_thread(_create)
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied writing to {skills_dir}")
    except Exception as e:
        logger.error(f"Failed to create skill '{skill_name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create skill: {e}")

    logger.info(f"Created skill '{skill_name}' for provider '{provider}' at {skill_dir}")
    return SuccessResponse(message=f"Skill '{skill_name}' created successfully")


@router.delete("/skills/{provider}/{skill_name}", response_model=SuccessResponse)
async def delete_skill(
    provider: str,
    skill_name: str,
    exec_user: str = Query(default="", description="Exec user for home directory resolution"),
    skills_path: Optional[str] = Query(default=None, description="Custom skills directory path"),
):
    """Delete a skill directory."""
    provider = (provider or "").strip().lower()
    skill_name = (skill_name or "").strip()

    if not skill_name or not _SKILL_NAME_RE.match(skill_name):
        raise HTTPException(status_code=400, detail="Invalid skill name")

    # Determine skills directory
    user = exec_user or settings.exec_user or "ubuntu"
    home_base = settings.user_home_base or "/home"
    user_home = Path(home_base) / user

    if skills_path:
        raw = skills_path
        if raw.startswith("~/") or raw == "~":
            skills_dir = user_home / raw[2:] if len(raw) > 2 else user_home
        else:
            skills_dir = Path(raw)
        if not skills_dir.is_absolute():
            raise HTTPException(status_code=400, detail="skills_path must be an absolute path")
    elif provider in _PROVIDER_CONFIG_DIRS:
        skills_dir = user_home / _PROVIDER_CONFIG_DIRS[provider] / "skills"
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider '{provider}'. Provide skills_path for custom aliases.",
        )

    skill_dir = (skills_dir / skill_name).resolve()
    if not str(skill_dir).startswith(str(skills_dir.resolve())):
        raise HTTPException(status_code=400, detail="Invalid skill path")

    def _delete():
        if not skill_dir.exists():
            raise FileNotFoundError(f"Skill '{skill_name}' not found at {skill_dir}")
        if not skill_dir.is_dir():
            raise ValueError(f"'{skill_dir}' is not a directory")
        shutil.rmtree(skill_dir)

    try:
        await asyncio.to_thread(_delete)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied deleting {skill_dir}")
    except Exception as e:
        logger.error(f"Failed to delete skill '{skill_name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete skill: {e}")

    logger.info(f"Deleted skill '{skill_name}' for provider '{provider}' at {skill_dir}")
    return SuccessResponse(message=f"Skill '{skill_name}' deleted successfully")
