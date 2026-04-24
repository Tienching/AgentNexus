# -*- coding: utf-8 -*-
"""Unified extension registry and bundled skill import APIs."""

from __future__ import annotations

import json
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..config import settings
from ..services.extension_registry import ExtensionRegistryService
from .nexus_auth import require_nexus_admin, verify_nexus_auth

router = APIRouter(
    prefix="/api/nexus/extensions",
    tags=["nexus-extensions"],
    dependencies=[Depends(verify_nexus_auth)],
)


class ExtensionProviderItem(BaseModel):
    name: str
    display_name: str
    installed: bool
    enabled: bool
    config_path: Optional[str] = None


class ExtensionSkillItem(BaseModel):
    name: str
    description: str = ""
    version: str = ""
    provider: str = ""
    source: str = "provider"
    path: str = ""


class ExtensionPluginItem(BaseModel):
    plugin_id: str
    name: str
    source: str
    path: str
    capabilities: List[str] = Field(default_factory=list)
    panels: List[str] = Field(default_factory=list)


class ExtensionPanelItem(BaseModel):
    panel_id: str
    title: str
    placement: str
    route: str
    capability: str


class ExtensionCatalogResponse(BaseModel):
    providers: List[ExtensionProviderItem] = Field(default_factory=list)
    plugins: List[ExtensionPluginItem] = Field(default_factory=list)
    bundled_skills: List[ExtensionSkillItem] = Field(default_factory=list)
    provider_skills: Dict[str, List[ExtensionSkillItem]] = Field(default_factory=dict)
    panels: List[ExtensionPanelItem] = Field(default_factory=list)


class ImportBundledSkillRequest(BaseModel):
    skill_name: str
    provider: str
    skills_path: Optional[str] = None
    overwrite: bool = False


def _service(exec_user: Optional[str] = None) -> ExtensionRegistryService:
    return ExtensionRegistryService(exec_user=exec_user or settings.exec_user)


@router.get("/catalog", response_model=ExtensionCatalogResponse)
async def get_extension_catalog(
    exec_user: str = Query(settings.exec_user),
    custom_paths: str = Query(default="", description="JSON-encoded dict of alias->skills_path"),
):
    custom_map: Dict[str, str] = {}
    if custom_paths:
        try:
            custom_map = json.loads(custom_paths)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid custom_paths JSON: {exc}") from exc
    payload = await _service(exec_user).get_catalog(custom_paths=custom_map)
    return ExtensionCatalogResponse(**payload)


@router.post("/skills/import", response_model=ExtensionSkillItem, status_code=201)
async def import_bundled_skill(
    request: ImportBundledSkillRequest,
    exec_user: str = Query(settings.exec_user),
    _admin=Depends(require_nexus_admin),
):
    service = _service(exec_user)
    try:
        skill = service.import_bundled_skill(
            skill_name=request.skill_name,
            provider=request.provider,
            skills_path=request.skills_path,
            overwrite=request.overwrite,
        )
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ExtensionSkillItem(**skill.to_dict())
