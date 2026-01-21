# -*- coding: utf-8 -*-
"""Chat streaming endpoint router"""

import json
import uuid
from fastapi import APIRouter, Request, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from ..models import RequestModel
from ..models.agui_events import AGUIRequest
from ..adapters import ProtocolType, get_router, detect_protocol, detect_protocol_from_body
from ..services.stream_handler import StreamHandler
from ..logger import get_logger

router = APIRouter(tags=["chat"])
logger = get_logger(__name__)


@router.post("/chat/stream", response_class=StreamingResponse)
async def chat_stream_default(request: Request):
    """默认 agent 的流式聊天入口。

    主要用于让 `/chat/stream` 这个路径存在，从而对 GET 返回 405（符合测试期望）。
    """
    return await chat_stream(request, agent_name="ubuntu")


@router.post("/chat/stream/{agent_name}", response_class=StreamingResponse)
async def chat_stream(request: Request, agent_name: str):
    """
    统一流式聊天接口（自动识别协议类型）

    支持两种协议格式：
    - 易事厅协议：传统格式，返回 event:delta 格式的 SSE
    - AG-UI 协议：标准 AG-UI 格式，返回 data: JSON 格式的 SSE

    Args:
        request: FastAPI请求对象
        agent_name: Linux系统用户名，通过su切换到该用户运行CCR命令
    """
    # 获取原始请求体
    try:
        body_bytes = await request.body()
        body_str = body_bytes.decode('utf-8')
    except Exception as e:
        logger.error(f"Failed to read request body: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to read request body"
        )
    
    # 记录完整请求信息
    logger.info(f"REQUEST BODY: {body_str if body_str else '(empty)'}")

    # 检查是否是测试连接请求（空body或仅包含{}）
    if not body_str or body_str.strip() in ['', '{}']:
        logger.info(f"Received test connectivity request for agent {agent_name} (empty body)")
        return await _handle_test_request(agent_name)

    # 解析请求体为 dict
    try:
        body_dict = json.loads(body_str)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON in request body"
        )
    
    # 检测协议类型
    protocol = detect_protocol(request)
    if protocol == ProtocolType.LEGACY:
        # 从请求体再次检测
        protocol = detect_protocol_from_body(body_dict)
    
    logger.info(
        f"Processing request with protocol {protocol.value}",
        extra={
            "agent_name": agent_name,
            "protocol": protocol.value,
        }
    )
    
    # 创建流处理器
    stream_handler = StreamHandler()
    
    # 根据协议类型处理请求
    if protocol == ProtocolType.AGUI:
        return await stream_handler.handle_agui_request(request, body_dict, agent_name)
    else:
        return await stream_handler.handle_legacy_request(request, body_str, body_dict, agent_name)


async def _handle_test_request(agent_name: str) -> StreamingResponse:
    """处理测试连接请求"""
    from ..services.ccr_executor import CCRExecutor
    
    executor = CCRExecutor()
    test_msg = f"Service is running with agent '{agent_name}'. This is a test response for connectivity check."

    async def test_response():
        """返回测试响应（易事厅格式）"""
        yield executor.format_legacy_sse(test_msg, finished=True, answer_success=1)

    return StreamingResponse(
        test_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Transfer-Encoding": "chunked",
        }
    )


@router.get("/agui/test")
async def agui_test():
    """AG-UI SSE 格式测试端点 - 返回标准的 AG-UI 事件序列"""
    test_thread_id = f"test-{uuid.uuid4()}"
    test_run_id = f"test-run-{uuid.uuid4()}"
    test_msg_id = f"test-msg-{uuid.uuid4()}"
    
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
        }
    )
