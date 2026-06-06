# -*- coding: utf-8 -*-
"""Chat streaming endpoint router"""

import json
import re
import uuid
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Request, HTTPException, status
from fastapi.responses import StreamingResponse

from src.runtime.stores.alias_registry import KNOWN_PROVIDERS, get_alias_registry

from ..services.stream_handler import StreamHandler
from ..logger import get_logger
from ..config import settings
from ..utils.ids import resolve_session_id, resolve_run_id, gen_run_id, gen_session_id

router = APIRouter(tags=["chat"])
logger = get_logger(__name__)

_SENSITIVE_FIELD_RE = re.compile(
    r"(authorization|token|secret|password|api[_-]?key|signature|credential|media[_-]?id)",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://[^\s\"'<>]+")


def _redact_url_for_log(value: str) -> str:
    """Keep URL shape for debugging while removing signed query values."""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return value

    query = urlencode(
        [(key, "<redacted>") for key, _value in parse_qsl(parsed.query, keep_blank_values=True)],
        doseq=True,
    )
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))


def _sanitize_debug_string(value: str) -> str:
    if value.startswith("wecom://media/"):
        return "wecom://media/<redacted>"
    if value.startswith(("http://", "https://")):
        return _redact_url_for_log(value)
    value = _URL_RE.sub(lambda match: _redact_url_for_log(match.group(0)), value)
    if len(value) > 1000:
        return value[:1000] + f"...[truncated, total: {len(value)} chars]"
    return value


def _sanitize_agui_debug_value(value: Any, key: str = "") -> Any:
    if _SENSITIVE_FIELD_RE.search(key):
        return "***REDACTED***"
    if isinstance(value, str):
        return _sanitize_debug_string(value)
    if isinstance(value, list):
        return [_sanitize_agui_debug_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(item_key): _sanitize_agui_debug_value(item_value, str(item_key))
            for item_key, item_value in value.items()
        }
    return value


def _has_agui_media_debug_signal(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"content_parts", "file_paths", "image_paths"} and item:
                return True
            if _has_agui_media_debug_signal(item):
                return True
    elif isinstance(value, list):
        return any(_has_agui_media_debug_signal(item) for item in value)
    elif isinstance(value, str):
        lowered = value.lower()
        return "wecom://media/" in lowered or "cos" in lowered or "q-signature" in lowered
    return False


def _summarize_agui_headers(request: Request) -> dict[str, str]:
    summary: dict[str, str] = {}
    for key, value in request.headers.items():
        key_lower = key.lower()
        if _SENSITIVE_FIELD_RE.search(key_lower) or key_lower in {"cookie", "set-cookie"}:
            summary[key_lower] = "***REDACTED***"
        elif key_lower.startswith(("x-", "ag-", "aegis-")) or key_lower in {
            "content-type",
            "user-agent",
            "host",
        }:
            summary[key_lower] = _sanitize_debug_string(str(value))
    return dict(sorted(summary.items()))


def _summarize_agui_part(part: Any) -> dict[str, Any]:
    if not isinstance(part, dict):
        return {"kind": type(part).__name__}
    url = part.get("url") or part.get("path")
    if not url and isinstance(part.get("image_url"), dict):
        url = part["image_url"].get("url")
    url_summary = None
    if isinstance(url, str) and url:
        if url.startswith(("http://", "https://")):
            parsed = urlsplit(url)
            url_summary = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        elif "://" in url:
            url_summary = f"{url.split('://', 1)[0]}://<redacted>"
        else:
            url_summary = "local-path"
    file_name = part.get("fileName") or part.get("file_name") or part.get("filename") or part.get("name")
    return {
        "type": part.get("type"),
        "mime": part.get("mimeType") or part.get("mime_type") or part.get("mediaType"),
        "file_name": file_name,
        "url": url_summary,
        "keys": sorted(str(key) for key in part.keys()),
    }


def _summarize_agui_body_shape(body_dict: dict[str, Any]) -> dict[str, Any]:
    last_user_content: Any = None
    messages = body_dict.get("messages")
    if isinstance(messages, list):
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "user":
                last_user_content = msg.get("content")
                break

    top_level_parts = body_dict.get("content_parts")
    if not isinstance(top_level_parts, list):
        top_level_parts = []
    message_parts = last_user_content if isinstance(last_user_content, list) else []

    return {
        "threadId": body_dict.get("threadId") or body_dict.get("session_id"),
        "runId": body_dict.get("runId") or body_dict.get("msg_id"),
        "has_top_level_content_parts": bool(top_level_parts),
        "top_level_parts": [_summarize_agui_part(part) for part in top_level_parts[:8]],
        "message_content_kind": type(last_user_content).__name__,
        "message_parts": [_summarize_agui_part(part) for part in message_parts[:8]],
        "file_paths_count": len(body_dict.get("file_paths") or []),
        "image_paths_count": len(body_dict.get("image_paths") or []),
    }


def _log_agui_debug_dump(request: Request, body_dict: dict[str, Any]) -> None:
    if not _has_agui_media_debug_signal(body_dict):
        return

    logger.info(
        "AG-UI media request boundary: "
        + json.dumps(
            {
                "headers": _summarize_agui_headers(request),
                "body_shape": _summarize_agui_body_shape(body_dict),
            },
            ensure_ascii=False,
        )
    )
    logger.info(
        "AG-UI request debug dump",
        extra={
            "agui_request_debug": _sanitize_agui_debug_value(body_dict),
        },
    )


def _normalize_selector(value: Any) -> str:
    return str(value or "").strip().lower()


def _resolve_provider_alias_target(provider_or_alias: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Resolve a provider/alias input into canonical provider + alias."""
    normalized = _normalize_selector(provider_or_alias)
    if not normalized:
        return None, None

    alias_registry = get_alias_registry()
    resolved_provider = alias_registry.resolve(normalized)
    if resolved_provider:
        return resolved_provider, normalized

    if normalized in KNOWN_PROVIDERS:
        return normalized, normalized

    inferred_provider = next(
        (provider_name for provider_name in sorted(KNOWN_PROVIDERS) if normalized.startswith(f"{provider_name}-")),
        None,
    )
    if inferred_provider:
        return inferred_provider, normalized

    return normalized, normalized


def _get_or_create_forwarded_props(body_dict: dict[str, Any]) -> dict[str, Any]:
    forwarded_props = body_dict.get("forwardedProps")
    if isinstance(forwarded_props, dict):
        return forwarded_props

    forwarded_props = {}
    body_dict["forwardedProps"] = forwarded_props
    return forwarded_props


def _upgrade_legacy_request(body_dict: dict[str, Any]) -> dict[str, Any]:
    """Convert minimal legacy requests into the AG-UI request shape."""
    content = str(body_dict.get("content") or "").strip()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Missing required field: content",
        )

    thread_id = resolve_session_id(body_dict.get("session_id"))
    run_id = resolve_run_id(body_dict.get("msg_id"))
    forwarded_props = {}

    original_forwarded = body_dict.get("forwardedProps")
    if isinstance(original_forwarded, dict):
        forwarded_props.update(original_forwarded)

    for forwarded_key, raw_value in {
        "username": body_dict.get("user"),
        "provider": body_dict.get("provider"),
        "alias": body_dict.get("alias"),
        "model": body_dict.get("model"),
    }.items():
        normalized_value = str(raw_value or "").strip()
        if normalized_value:
            forwarded_props.setdefault(forwarded_key, normalized_value)

    agui_body = {
        "threadId": thread_id,
        "runId": run_id,
        "messages": [
            {"id": run_id, "role": "user", "content": content}
        ],
        "forwardedProps": forwarded_props,
    }

    provider = str(body_dict.get("provider") or "").strip()
    if provider:
        agui_body["provider"] = provider

    for passthrough_key in ("cwd", "cwd_mode", "run_kind", "cli_session_id", "image_paths", "file_paths", "content_parts"):
        if passthrough_key in body_dict and body_dict.get(passthrough_key) not in (None, "", [], {}):
            agui_body[passthrough_key] = body_dict.get(passthrough_key)

    return agui_body


def _apply_query_provider_alias(request: Request, body_dict: dict[str, Any]) -> dict[str, Any]:
    """Inject query-level provider/alias selection into the request body."""
    try:
        query_provider = _normalize_selector(request.query_params.get("provider", ""))
        query_alias = _normalize_selector(request.query_params.get("alias", ""))
    except Exception:
        return body_dict

    if not query_provider and not query_alias:
        return body_dict

    forwarded_props = _get_or_create_forwarded_props(body_dict)

    if query_alias:
        resolved_provider, resolved_alias = _resolve_provider_alias_target(query_alias)
        query_alias = resolved_alias or query_alias
        if not query_provider:
            query_provider = _normalize_selector(resolved_provider)

    if query_provider:
        body_dict["provider"] = query_provider
        forwarded_props["provider"] = query_provider
    if query_alias:
        body_dict["alias"] = query_alias
        forwarded_props["alias"] = query_alias

    logger.info(
        "Applied query-level provider/alias override",
        extra={
            "query_provider": query_provider,
            "query_alias": query_alias,
        },
    )
    return body_dict


@router.post("/chat/stream", response_class=StreamingResponse)
async def chat_stream_default(request: Request):
    """默认 agent 的流式聊天入口。

    主要用于让 `/chat/stream` 这个路径存在，从而对 GET 返回 405（符合测试期望）。
    """
    return await chat_stream(request, exec_user=settings.exec_user)


@router.post("/chat/stream/{exec_user}", response_class=StreamingResponse)
async def chat_stream(request: Request, exec_user: str):
    """
    统一流式聊天接口（AG-UI 协议）

    Args:
        request: FastAPI请求对象
        exec_user: Linux系统用户名，通过su切换到该用户运行CLI命令
    """
    # 获取原始请求体
    try:
        body_bytes = await request.body()
        body_str = body_bytes.decode("utf-8")
    except Exception as e:
        logger.error(f"Failed to read request body: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to read request body",
        )

    # 仅记录请求元数据，不记录完整请求体（避免 PII/凭证泄露）
    logger.info(
        "Received chat request",
        extra={
            "exec_user": exec_user,
            "body_length": len(body_str) if body_str else 0,
        },
    )

    # 检查是否是测试连接请求（空body或仅包含{}）
    if not body_str or body_str.strip() in ["", "{}"]:
        logger.info(f"Received test connectivity request for exec_user {exec_user} (empty body)")
        return await _handle_test_request()

    # 解析请求体为 dict
    try:
        body_dict = json.loads(body_str)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON in request body",
        )

    if not isinstance(body_dict, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body must be a JSON object",
        )

    _log_agui_debug_dump(request, body_dict)

    # 兼容 legacy/minimal 请求：仅包含 user/content
    if "threadId" not in body_dict and "runId" not in body_dict:
        body_dict = _upgrade_legacy_request(body_dict)

    body_dict = _apply_query_provider_alias(request, body_dict)

    logger.info(
        "Processing request with AG-UI protocol",
        extra={
            "exec_user": exec_user,
            "protocol": "agui",
        },
    )

    # 创建流处理器并处理 AG-UI 请求
    stream_handler = StreamHandler()
    return await stream_handler.handle_agui_request(request, body_dict, exec_user)


@router.post("/{port_prefix}/chat/stream/{exec_user}", response_class=StreamingResponse, include_in_schema=False)
async def chat_stream_with_port_prefix(request: Request, port_prefix: str, exec_user: str):
    """兼容误把端口 `:8081` 拼到 path 里的旧前端请求。"""
    if not port_prefix.startswith(":") or not port_prefix[1:].isdigit():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    logger.warning(
        "Received chat stream request with port-like path prefix; normalizing",
        extra={"port_prefix": port_prefix, "exec_user": exec_user},
    )
    return await chat_stream(request, exec_user=exec_user)


async def _handle_test_request() -> StreamingResponse:
    """处理测试连接请求 - 返回 AG-UI 格式响应"""
    test_run_id = f"test-{uuid.uuid4()}"
    test_msg_id = f"test-msg-{uuid.uuid4()}"

    async def test_response():
        """返回 AG-UI 格式测试响应"""
        yield f'data: {{"type":"RUN_STARTED","runId":"{test_run_id}"}}\n\n'
        yield f'data: {{"type":"TEXT_MESSAGE_START","messageId":"{test_msg_id}","role":"assistant"}}\n\n'
        yield f'data: {{"type":"TEXT_MESSAGE_CONTENT","messageId":"{test_msg_id}","delta":"Service is running. This is a test response for connectivity check."}}\n\n'
        yield f'data: {{"type":"TEXT_MESSAGE_END","messageId":"{test_msg_id}"}}\n\n'
        yield f'data: {{"type":"RUN_FINISHED","runId":"{test_run_id}"}}\n\n'

    return StreamingResponse(
        test_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Transfer-Encoding": "chunked",
        },
    )


@router.get("/agui/test")
async def agui_test():
    """AG-UI SSE 格式测试端点 - 返回标准的 AG-UI 事件序列"""
    test_thread_id = gen_session_id()
    test_run_id = gen_run_id()
    test_msg_id = f"test-msg-{gen_run_id()}"

    async def generate_test_events():
        # RUN_STARTED
        yield f'data: {{"type":"RUN_STARTED","threadId":"{test_thread_id}","runId":"{test_run_id}"}}\n\n'
        # TEXT_MESSAGE_START
        yield f'data: {{"type":"TEXT_MESSAGE_START","messageId":"{test_msg_id}","role":"assistant"}}\n\n'
        # TEXT_MESSAGE_CONTENT
        yield f'data: {{"type":"TEXT_MESSAGE_CONTENT","messageId":"{test_msg_id}","delta":"This is a test message."}}\n\n'
        # TEXT_MESSAGE_END
        yield f'data: {{"type":"TEXT_MESSAGE_END","messageId":"{test_msg_id}"}}\n\n'
        # RUN_FINISHED
        yield f'data: {{"type":"RUN_FINISHED","threadId":"{test_thread_id}","runId":"{test_run_id}"}}\n\n'

    return StreamingResponse(
        generate_test_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
