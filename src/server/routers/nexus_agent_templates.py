# -*- coding: utf-8 -*-
"""Configurable agent template API for the top-level Agents page."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from ..services.agent_templates import AgentTemplateError, get_agent_template_store
from .nexus_auth import verify_nexus_auth
from .nexus_models import SuccessResponse

router = APIRouter(
    prefix="/api/nexus",
    tags=["nexus-agent-templates"],
    dependencies=[Depends(verify_nexus_auth)],
)


class ToolConfigSchema(BaseModel):
    baseTools: Optional[list[str]] = None
    deferredTools: Optional[list[str]] = None
    disabledTools: Optional[list[str]] = None
    mcp: Optional[list[str]] = None


class AgentTemplateCreateRequest(BaseModel):
    name: str = Field(..., description="Unique kebab-case template name")
    role: str = Field(..., description="Human-readable role")
    systemPrompt: str = Field(..., description="System prompt markdown")
    description: str = ""
    version: str = "v1"
    language: str = "zh-CN"
    avatarUrl: Optional[str] = None
    modelProvider: Optional[str] = None
    modelName: Optional[str] = None
    temperature: float = 0.7
    topP: float = 1.0
    maxTokens: Optional[int] = None
    maxIterations: int = 15
    toolConfig: Optional[ToolConfigSchema | dict[str, Any]] = None
    skillConfig: Optional[dict[str, Any]] = None
    knowledgeConfig: Optional[dict[str, Any]] = None
    triggerMode: str = "reactive"
    schedule: Optional[dict[str, Any]] = None
    eventSubscriptions: Optional[list[dict[str, Any]]] = None
    surfaces: Optional[list[str]] = None
    capabilities: Optional[list[str]] = None
    guardrails: Optional[dict[str, Any]] = None
    createdBy: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return value.strip()


class AgentTemplatePatchRequest(BaseModel):
    role: Optional[str] = None
    systemPrompt: Optional[str] = None
    description: Optional[str] = None
    version: Optional[str] = None
    language: Optional[str] = None
    avatarUrl: Optional[str] = None
    modelProvider: Optional[str] = None
    modelName: Optional[str] = None
    temperature: Optional[float] = None
    topP: Optional[float] = None
    maxTokens: Optional[int] = None
    maxIterations: Optional[int] = None
    toolConfig: Optional[ToolConfigSchema | dict[str, Any]] = None
    skillConfig: Optional[dict[str, Any]] = None
    knowledgeConfig: Optional[dict[str, Any]] = None
    triggerMode: Optional[str] = None
    schedule: Optional[dict[str, Any]] = None
    eventSubscriptions: Optional[list[dict[str, Any]]] = None
    surfaces: Optional[list[str]] = None
    capabilities: Optional[list[str]] = None
    guardrails: Optional[dict[str, Any]] = None
    createdBy: Optional[str] = None


class AgentTemplateListResponse(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0


def _raise_template_error(exc: AgentTemplateError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc)},
    ) from exc


def _request_payload(model: BaseModel, *, exclude_unset: bool) -> dict[str, Any]:
    payload = model.model_dump(exclude_unset=exclude_unset)
    tool_config = payload.get("toolConfig")
    if isinstance(tool_config, BaseModel):
        payload["toolConfig"] = tool_config.model_dump(exclude_none=True)
    return payload


@router.get("/agent-templates", response_model=AgentTemplateListResponse)
async def list_agent_templates(source: Optional[str] = Query(default=None)):
    """List configurable agent templates."""
    store = get_agent_template_store()
    try:
        items = store.list_templates(source=source)
    except AgentTemplateError as exc:
        _raise_template_error(exc)
    return AgentTemplateListResponse(items=items, total=len(items))


@router.get("/agent-templates/{name}")
async def get_agent_template(name: str):
    """Return one agent template by name."""
    store = get_agent_template_store()
    try:
        template = store.get(name)
    except AgentTemplateError as exc:
        _raise_template_error(exc)
    if template is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "AGENT_TEMPLATE_NOT_FOUND", "message": f"模板不存在: {name}"},
        )
    return template


@router.post("/agent-templates", status_code=201)
async def create_agent_template(request: AgentTemplateCreateRequest):
    """Create a custom agent template."""
    store = get_agent_template_store()
    try:
        return store.create(_request_payload(request, exclude_unset=True), created_by=request.createdBy)
    except AgentTemplateError as exc:
        _raise_template_error(exc)


@router.patch("/agent-templates/{name}")
async def patch_agent_template(name: str, request: AgentTemplatePatchRequest):
    """Update an existing agent template."""
    store = get_agent_template_store()
    try:
        return store.patch(name, _request_payload(request, exclude_unset=True))
    except AgentTemplateError as exc:
        _raise_template_error(exc)


@router.delete("/agent-templates/{name}", response_model=SuccessResponse)
async def delete_agent_template(name: str):
    """Delete a custom or preset copy from the editable template registry."""
    store = get_agent_template_store()
    try:
        store.delete(name)
    except AgentTemplateError as exc:
        _raise_template_error(exc)
    return SuccessResponse(message=f"Agent template deleted: {name}")


@router.post("/agent-templates/{name}/reset")
async def reset_agent_template(name: str):
    """Reset a preset template from ``agent/templates``."""
    store = get_agent_template_store()
    try:
        return store.reset(name)
    except AgentTemplateError as exc:
        _raise_template_error(exc)
