# -*- coding: utf-8 -*-
"""Channel webhook 路由"""

import json
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from ..services.channel_service import get_channel_service

router = APIRouter(prefix="/api/channels", tags=["channels"])


def _get_channel(channel_name: str):
    """Get a channel by name or raise appropriate HTTP errors."""
    service = get_channel_service()
    if not service or not service.manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Channel service not initialized",
        )
    channel = service.manager.get_channel(channel_name)
    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{channel_name} channel not configured",
        )
    return channel


async def _handle_wecom_verify(request: Request, channel_name: str):
    """Shared GET handler for WeCom-style URL verification."""
    from fastapi.responses import PlainTextResponse

    channel = _get_channel(channel_name)
    msg_signature = request.query_params.get("msg_signature", "")
    timestamp = request.query_params.get("timestamp", "")
    nonce = request.query_params.get("nonce", "")
    echostr = request.query_params.get("echostr", "")

    result = channel.verify_url(msg_signature, timestamp, nonce, echostr)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="URL verification failed",
        )
    return PlainTextResponse(result)


async def _handle_wecom_post(request: Request, channel_name: str):
    """Shared POST handler for WeCom-style webhook callbacks."""
    channel = _get_channel(channel_name)
    body = await request.body()
    query_params = {
        "msg_signature": request.query_params.get("msg_signature", ""),
        "timestamp": request.query_params.get("timestamp", ""),
        "nonce": request.query_params.get("nonce", ""),
    }
    result = await channel.handle_webhook(body, dict(request.headers), query_params)
    if result is not None and isinstance(result, dict):
        return JSONResponse(result)
    return JSONResponse({"ok": True})


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


@router.post("/feishu/webhook")
async def feishu_webhook(request: Request):
    """飞书 Webhook 入口

    处理飞书事件订阅回调，包括 URL 验证和消息事件。
    """
    service = get_channel_service()
    if not service or not service.manager:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Channel service not initialized",
        )

    channel = service.manager.get_channel("feishu")
    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feishu channel not configured",
        )

    body = await request.body()

    # 先检查是否是 URL 验证 challenge
    try:
        payload = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        )

    # 处理 challenge 验证
    challenge_resp = channel.get_challenge_response(payload)
    if challenge_resp:
        return JSONResponse(challenge_resp)

    # 处理正常事件
    handled = await channel.handle_webhook(body, dict(request.headers))
    if not handled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook event",
        )

    return JSONResponse({"ok": True})


@router.get("/wecom/webhook")
async def wecom_webhook_verify(request: Request):
    """企业微信智能机器人 URL 验证入口 (GET)"""
    return await _handle_wecom_verify(request, "wecom")


@router.post("/wecom/webhook")
async def wecom_webhook(request: Request):
    """企业微信智能机器人消息回调入口 (POST)"""
    return await _handle_wecom_post(request, "wecom")


@router.get("/wecom_bot/webhook")
async def wecom_bot_webhook_verify(request: Request):
    """企业微信普通机器人 URL 验证入口 (GET)"""
    return await _handle_wecom_verify(request, "wecom_bot")


@router.post("/wecom_bot/webhook")
async def wecom_bot_webhook(request: Request):
    """企业微信普通机器人消息回调入口 (POST)"""
    return await _handle_wecom_post(request, "wecom_bot")
