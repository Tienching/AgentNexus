# -*- coding: utf-8 -*-
"""Stream Handler Service

Handle AG-UI and Legacy protocol streaming responses
"""

import asyncio
import json
import time
from typing import Dict, Any, List

from fastapi import Request, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from ..models import RequestModel
from ..models.agui_events import AGUIRequest
from ..adapters import ProtocolType, get_router
from ..logger import get_logger
from .ccr_executor import CCRExecutor
from .callback_handler import CallbackHandler

logger = get_logger(__name__)


class StreamHandler:
    """流式处理器"""

    def __init__(self):
        self.executor = CCRExecutor()
        self.callback_handler = CallbackHandler()

    async def handle_agui_request(
        self, 
        request: Request, 
        body_dict: Dict[str, Any], 
        agent_name: str
    ) -> StreamingResponse:
        """处理 AG-UI 协议请求"""
        router = get_router()
        adapter = router.get_adapter(ProtocolType.AGUI)
        
        try:
            agui_request = AGUIRequest.model_validate(body_dict)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid AG-UI request: {str(e)}"
            )
        
        legacy_data = agui_request.to_legacy_request()
        request_model = RequestModel.model_validate(legacy_data)
        
        adapter.init_state(
            thread_id=agui_request.threadId,
            run_id=agui_request.runId
        )
        
        # 提取 response_url
        response_url = agui_request.get_response_url()
        
        logger.info(
            "AG-UI request converted",
            extra={
                "thread_id": agui_request.threadId,
                "run_id": agui_request.runId,
                "user": request_model.user,
                "has_response_url": bool(response_url),
            }
        )
        
        if not request_model.user or not request_model.content:
            missing_fields = []
            if not request_model.user:
                missing_fields.append("user (or forwardedProps.username for AG-UI)")
            if not request_model.content:
                missing_fields.append("content (or messages for AG-UI)")
            
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Missing required fields: {', '.join(missing_fields)}"
            )
        
        # 如果有 response_url，启用超时回调模式
        if response_url:
            return await self._stream_agui_with_callback(
                request, request_model, agui_request, adapter, agent_name
            )
        
        # 标准 AG-UI 流式处理
        async def generate_agui():
            """生成 AG-UI 格式的 SSE 流"""
            event_count = 0
            try:
                start_event = adapter.create_start_event()
                if start_event:
                    event_count += 1
                    yield start_event
                
                async for line in self.executor.execute(request_model, agent_name=agent_name, output_format="raw"):
                    if not line.strip():
                        continue
                    
                    try:
                        event_data = json.loads(line)
                        converted = adapter.convert(event_data)
                        if converted:
                            for event_line in converted.split('\n\n'):
                                if event_line.strip():
                                    event_count += 1
                            yield converted
                    except json.JSONDecodeError:
                        logger.warning(f"AG-UI JSON decode error: {line[:200]}")
                        continue
                    except Exception as e:
                        logger.warning(f"AG-UI convert error: {e}")
                        continue
                
                end_event = adapter.create_end_event()
                if end_event:
                    for event_line in end_event.split('\n\n'):
                        if event_line.strip():
                            event_count += 1
                    yield end_event
                
                logger.info(f"AG-UI stream completed, total events: {event_count}")
                    
            except Exception as e:
                logger.error(f"AG-UI stream error: {e}", exc_info=True)
                error_event = adapter.create_error_event(str(e))
                yield error_event
        
        return StreamingResponse(
            generate_agui(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "Transfer-Encoding": "chunked",
            },
        )

    async def _stream_agui_with_callback(
        self,
        request: Request,
        request_model: RequestModel,
        agui_request: AGUIRequest,
        adapter,
        agent_name: str,
    ) -> StreamingResponse:
        """支持超时回调的 AG-UI 流式处理
        
        在 5分30秒 时发送超时提示并结束 SSE 流，
        后台继续收集 CCR 回复，完成后通过 response_url 发送剩余结果。
        """
        STREAM_TIMEOUT = 330  # 5分30秒
        
        response_url = agui_request.get_response_url()
        msg_id = agui_request.get_msg_id()
        
        message_queue: asyncio.Queue = asyncio.Queue()
        
        stream_state = {
            "client_disconnected": False,
            "stream_timeout": False,
            "all_events": [],      # 所有 AG-UI 事件
            "sent_count": 0,       # 已发送的事件数
            "producer_done": False,
            "start_time": time.time(),
        }
        
        async def producer():
            """后台生产者：执行 CCR 并收集事件"""
            try:
                async for line in self.executor.execute(request_model, agent_name=agent_name, output_format="raw"):
                    if not line.strip():
                        continue
                    
                    try:
                        event_data = json.loads(line)
                        converted = adapter.convert(event_data)
                        if converted:
                            # 保存事件
                            for event_str in converted.split('\n\n'):
                                if event_str.strip():
                                    stream_state["all_events"].append(event_str + '\n\n')
                            
                            await message_queue.put(("events", converted))
                    except json.JSONDecodeError:
                        logger.warning(f"AG-UI JSON decode error: {line[:200]}")
                        continue
                    except Exception as e:
                        logger.warning(f"AG-UI convert error: {e}")
                        continue
                        
            except Exception as e:
                logger.error(f"AG-UI producer error: {e}", exc_info=True)
                await message_queue.put(("error", str(e)))
            finally:
                stream_state["producer_done"] = True
                await message_queue.put(("done", None))
                
                # 如果超时或断开，发送剩余事件到 response_url
                if (stream_state["stream_timeout"] or stream_state["client_disconnected"]) and response_url:
                    pending_events = stream_state["all_events"][stream_state["sent_count"]:]
                    if pending_events:
                        logger.info(
                            "Sending remaining AG-UI events via callback",
                            extra={
                                "pending_count": len(pending_events),
                                "total_count": len(stream_state["all_events"]),
                            }
                        )
                        await self.callback_handler.send_agui_callback(
                            response_url,
                            pending_events,
                            {
                                "user": request_model.user,
                                "msg_id": msg_id or request_model.msg_id,
                                "session_id": request_model.session_id,
                                "content": request_model.content,
                            }
                        )
        
        producer_task = asyncio.create_task(producer())
        
        async def generate():
            """生成 AG-UI SSE 流"""
            event_count = 0
            try:
                # 发送开始事件
                start_event = adapter.create_start_event()
                if start_event:
                    event_count += 1
                    yield start_event
                
                while True:
                    elapsed_time = time.time() - stream_state["start_time"]
                    
                    # 超时检查
                    if elapsed_time >= STREAM_TIMEOUT:
                        logger.info("AG-UI stream timeout reached, switching to background processing")
                        stream_state["stream_timeout"] = True
                        
                        # 发送超时提示
                        timeout_msg = "\n\n---\n⏰ **处理时间较长，已转为后台处理**\n\n内容较多，为避免连接超时，已转为后台继续处理。处理完成后会将完整结果发送给您，请耐心等待。\n"
                        
                        from ..models.agui_events import TextMessageContentEvent, TextMessageEndEvent, RunFinishedEvent
                        
                        # 确保有消息 ID
                        if not adapter.state.message_started:
                            adapter.state.current_message_id = f"timeout-msg-{agui_request.runId}"
                            adapter.state.message_started = True
                            from ..models.agui_events import TextMessageStartEvent, MessageRole
                            msg_start = TextMessageStartEvent(
                                messageId=adapter.state.current_message_id,
                                role=MessageRole.ASSISTANT
                            )
                            yield msg_start.to_sse()
                        
                        # 发送超时提示内容
                        content_event = TextMessageContentEvent(
                            messageId=adapter.state.current_message_id,
                            delta=timeout_msg
                        )
                        yield content_event.to_sse()
                        
                        # 发送消息结束
                        msg_end = TextMessageEndEvent(messageId=adapter.state.current_message_id)
                        yield msg_end.to_sse()
                        
                        # 发送运行结束
                        run_finished = RunFinishedEvent(
                            threadId=agui_request.threadId,
                            runId=agui_request.runId
                        )
                        yield run_finished.to_sse()
                        
                        return
                    
                    # 检查客户端断开
                    if await request.is_disconnected():
                        logger.info("AG-UI client disconnected during streaming")
                        stream_state["client_disconnected"] = True
                        return
                    
                    # 获取消息
                    try:
                        msg_type, msg_data = await asyncio.wait_for(
                            message_queue.get(),
                            timeout=1.0
                        )
                    except asyncio.TimeoutError:
                        continue
                    
                    if msg_type == "done":
                        # 正常完成，发送结束事件
                        end_event = adapter.create_end_event()
                        if end_event:
                            yield end_event
                        break
                    elif msg_type == "error":
                        error_event = adapter.create_error_event(f"处理错误: {msg_data}")
                        yield error_event
                        break
                    elif msg_type == "events":
                        yield msg_data
                        stream_state["sent_count"] = len(stream_state["all_events"])
                        event_count += msg_data.count('\n\n')
                
                logger.info(f"AG-UI stream with callback completed, events sent: {event_count}")
                
            except asyncio.CancelledError:
                logger.info("AG-UI stream generator cancelled")
                stream_state["client_disconnected"] = True
            except Exception as e:
                logger.error(f"AG-UI stream generation error: {e}", exc_info=True)
        
        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "Transfer-Encoding": "chunked",
            },
        )

    async def handle_legacy_request(
        self, 
        request: Request, 
        body_str: str, 
        body_dict: Dict[str, Any], 
        agent_name: str
    ) -> StreamingResponse:
        """处理易事厅协议请求"""
        try:
            request_model = RequestModel.model_validate(body_dict)
        except ValidationError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "Request validation failed", "validation_errors": e.errors()}
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to parse request: {str(e)}"
            )

        if not request_model.user or not request_model.content:
            missing_fields = []
            if not request_model.user:
                missing_fields.append("user")
            if not request_model.content:
                missing_fields.append("content")

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Missing required fields: {', '.join(missing_fields)}"
            )

        # 提取 response_url
        response_url = self._extract_response_url(request_model)

        if response_url:
            return await self._stream_with_disconnect_callback(request, request_model, agent_name)

        # 简单流式处理
        async def generate():
            try:
                async for chunk in self.executor.execute(request_model, agent_name=agent_name, output_format="legacy"):
                    yield chunk
            except Exception as e:
                logger.error(f"Stream generation error: {e}", exc_info=True)
                yield self.executor.format_legacy_error(f"处理错误: {e}")

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Transfer-Encoding": "chunked",
            },
        )

    def _extract_response_url(self, request_model: RequestModel) -> str:
        """从请求中提取 response_url"""
        response_url = request_model.response_url
        if not response_url and request_model.raw_msg:
            try:
                raw_msg_data = json.loads(request_model.raw_msg)
                if isinstance(raw_msg_data, dict):
                    response_url = raw_msg_data.get("response_url", "")
                    if not response_url and "rawData" in raw_msg_data:
                        raw_data = raw_msg_data.get("rawData", {})
                        if isinstance(raw_data, dict):
                            response_url = raw_data.get("response_url", "")
                if response_url:
                    request_model.response_url = response_url
                    logger.info("Extracted response_url from raw_msg")
            except json.JSONDecodeError:
                pass
            except Exception as e:
                logger.warning(f"Error extracting response_url from raw_msg: {e}")
        return response_url

    async def _stream_with_disconnect_callback(
        self,
        request: Request,
        request_model: RequestModel,
        agent_name: str,
    ) -> StreamingResponse:
        """支持客户端断开后回调的流式处理"""
        STREAM_TIMEOUT = 330
        RESPONSE_URL_TIMEOUT = 3600 - 20

        message_queue: asyncio.Queue = asyncio.Queue()

        stream_state = {
            "client_disconnected": False,
            "stream_timeout": False,
            "response_url_timeout": False,
            "all_messages": [],
            "sent_count": 0,
            "producer_done": False,
            "start_time": time.time(),
        }

        async def producer():
            try:
                async for chunk in self.executor.execute(request_model, agent_name=agent_name, output_format="legacy"):
                    elapsed_time = time.time() - stream_state["start_time"]
                    if elapsed_time >= RESPONSE_URL_TIMEOUT and not stream_state["response_url_timeout"]:
                        stream_state["response_url_timeout"] = True
                        logger.warning("Response URL timeout approaching")
                        await self.callback_handler.send_timeout_callback(
                            request_model.response_url,
                            request_model.user,
                            request_model.msg_id,
                            request_model.session_id,
                            request_model.content,
                            agent_name,
                        )
                        continue

                    try:
                        if chunk.startswith("event:delta\ndata:"):
                            data_str = chunk.replace("event:delta\ndata:", "").strip()
                            data = json.loads(data_str)
                            response_text = data.get("response", "")
                            if response_text:
                                stream_state["all_messages"].append(response_text)
                    except Exception:
                        pass

                    await message_queue.put(("chunk", chunk))

            except Exception as e:
                logger.error(f"Producer error: {e}", exc_info=True)
                await message_queue.put(("error", str(e)))
            finally:
                stream_state["producer_done"] = True
                await message_queue.put(("done", None))

                if (stream_state["client_disconnected"] or stream_state["stream_timeout"]) and \
                   stream_state["all_messages"] and not stream_state["response_url_timeout"]:
                    pending_messages = stream_state["all_messages"][stream_state["sent_count"]:]
                    if pending_messages:
                        await self.callback_handler.send_disconnect_callback(
                            request_model.response_url,
                            pending_messages,
                            request_model.user,
                            request_model.msg_id,
                            request_model.session_id,
                            request_model.content,
                            agent_name,
                        )

        producer_task = asyncio.create_task(producer())

        async def generate():
            try:
                while True:
                    elapsed_time = time.time() - stream_state["start_time"]
                    if elapsed_time >= STREAM_TIMEOUT:
                        logger.info("Stream timeout reached, switching to background processing")
                        stream_state["stream_timeout"] = True

                        yield self.executor.format_legacy_sse(
                            "\n\n---\n⏰ **处理时间较长，已转为后台处理**\n\n内容较多，为避免连接超时，已转为后台继续处理。处理完成后会将完整结果发送给您，请耐心等待（最迟一小时内返回结果）。\n",
                            finished=True,
                            answer_success=1
                        )
                        return

                    if await request.is_disconnected():
                        logger.info("Client disconnected during streaming")
                        stream_state["client_disconnected"] = True
                        return

                    try:
                        msg_type, msg_data = await asyncio.wait_for(
                            message_queue.get(),
                            timeout=1.0
                        )
                    except asyncio.TimeoutError:
                        continue

                    if msg_type == "done":
                        break
                    elif msg_type == "error":
                        yield self.executor.format_legacy_error(f"处理错误: {msg_data}")
                        break
                    elif msg_type == "chunk":
                        yield msg_data
                        stream_state["sent_count"] = len(stream_state["all_messages"])

            except asyncio.CancelledError:
                logger.info("Stream generator cancelled")
                stream_state["client_disconnected"] = True
            except Exception as e:
                logger.error(f"Stream generation error: {e}", exc_info=True)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "Transfer-Encoding": "chunked",
            },
        )
