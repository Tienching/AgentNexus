# -*- coding: utf-8 -*-
"""Channel webhook 路由"""

import json
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from ..services.channel_service import get_channel_service

router = APIRouter(prefix="/api/channels", tags=["channels"])


@router.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    """Telegram Webhook 入口"""
    service = get_channel_service()
    if not service or not service.manager:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Channel service not initialized")

    channel = service.manager.get_channel("telegram")
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Telegram channel not configured")

    if getattr(channel.config, "webhook_secret", None):
        secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if not secret or secret != channel.config.webhook_secret:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret")

    try:
        from telegram import Update
    except Exception:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Telegram SDK not available")

    if not getattr(channel, "_app", None):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Telegram app not initialized")

    payload = await request.json()
    update = Update.de_json(payload, channel._app.bot)
    await channel._app.process_update(update)
    return JSONResponse({"ok": True})


@router.post("/slack/webhook")
async def slack_webhook(request: Request):
    """Slack Webhook 入口（HTTP 模式）"""
    service = get_channel_service()
    if not service or not service.manager:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Channel service not initialized")

    channel = service.manager.get_channel("slack")
    if not channel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Slack channel not configured")

    body = await request.body()
    payload = None
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        payload = None

    if payload and payload.get("type") == "url_verification":
        return JSONResponse({"challenge": payload.get("challenge")})

    handled = await channel.handle_webhook(body, dict(request.headers))
    if not handled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook")

    return JSONResponse({"ok": True})
