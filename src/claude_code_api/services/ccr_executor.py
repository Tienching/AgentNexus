# -*- coding: utf-8 -*-
"""CCR Command Executor Service

Responsibilities:
- Build and execute CCR commands
- Process streaming output
- 格式化 SSE 响应
"""

import asyncio
import json
import shlex
import time
import re
import uuid
import os
import pwd
from pathlib import Path
from typing import AsyncGenerator, List, Dict, Any, Optional

from ..models import RequestModel
from ..models.agui_events import (
    TextMessageStartEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    RunStartedEvent,
    RunFinishedEvent,
    RunErrorEvent,
    MessageRole,
)
from ..config import settings
from ..logger import get_logger
from .user_directory import UserDirectoryManager

logger = get_logger(__name__)

# Debug模式：将完整的stream-json输出保存到文件
DEBUG_STREAM = os.environ.get("DEBUG_STREAM", "0") == "1"
DEBUG_STREAM_FILE = os.environ.get("DEBUG_STREAM_FILE", "/tmp/debug_stream.jsonl")


class CCRExecutor:
    """CCR 命令执行器"""

    def __init__(self, config=None):
        self.config = config or settings
        self.user_dir_manager = UserDirectoryManager(config)

    async def execute(
        self, 
        request: RequestModel, 
        agent_name: str,
        output_format: str = "raw"
    ) -> AsyncGenerator[str, None]:
        """
        执行 CCR 命令并生成流式输出

        Args:
            request: 请求模型
            agent_name: Linux系统用户名
            output_format: 输出格式 - "raw"(原始JSON行), "legacy"(易事厅格式)

        Yields:
            原始JSON行或格式化的SSE
        """
        start_time = time.time()

        # 验证用户参数
        if not request.user:
            logger.error(f"Missing required user parameter", extra={"agent_name": agent_name})
            raise ValueError("用户名参数是必需的，请在请求中提供 'user' 字段")

        # 获取session_id
        session_id = request.session_id if request.session_id else "default"

        # 确保用户目录存在
        user_dir = await self.user_dir_manager.ensure_directory(agent_name, request.user, session_id)
        logger.info(
            f"Using user directory",
            extra={
                "api_user": request.user,
                "agent_name": agent_name,
                "session_id": session_id,
                "user_dir": str(user_dir),
            }
        )

        # 清理输入内容
        cleaned_content = self._clean_content(request.content)

        # 检查管理员命令
        if self._check_for_admin_command(cleaned_content):
            if cleaned_content.lower() == "/clear":
                await self.user_dir_manager.clear_directory(agent_name, request.user, user_dir, session_id)
                user_dir = await self.user_dir_manager.ensure_directory(agent_name, request.user, session_id)

        # 构建命令
        cmd = self._build_command(agent_name, cleaned_content)

        # 检查当前用户
        current_user = pwd.getpwuid(os.getuid()).pw_name
        ccr_cmd_str = ' '.join(shlex.quote(arg) for arg in cmd)
        full_cmd = f"cd {shlex.quote(str(user_dir))} && {ccr_cmd_str}"
        
        if current_user == agent_name:
            cmd = ["bash", "-c", full_cmd]
            logger.info(f"Running command directly as current user", extra={
                "agent_name": agent_name,
                "api_user": request.user,
                "user_dir": str(user_dir),
            })
        else:
            cmd = ["su", "-", agent_name, "-c", full_cmd]
            logger.info(f"Wrapping command with su for agent {agent_name}", extra={
                "agent_name": agent_name,
                "api_user": request.user,
                "user_dir": str(user_dir),
            })

        logger.info(f"Starting CCR processing", extra={
            "process_type": "ccr_start",
            "api_user": request.user,
            "agent_name": agent_name,
            "content_preview": cleaned_content[:100] if len(cleaned_content) > 100 else cleaned_content,
        })

        try:
            # 创建子进程
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=10 * 1024 * 1024,
            )

            # 处理流式输出
            async for output in self._process_stream(process, request, output_format):
                yield output

            # 等待进程结束
            await asyncio.wait_for(process.wait(), timeout=self.config.ccr_timeout)

            duration = time.time() - start_time
            logger.info(f"CCR processing completed", extra={
                "process_type": "ccr_complete",
                "duration_ms": int(duration * 1000),
            })

        except asyncio.TimeoutError:
            logger.error(f"CCR command timeout", extra={"timeout_seconds": self.config.ccr_timeout})
            if output_format == "legacy":
                yield self.format_legacy_error("处理超时，请重试")
            else:
                yield json.dumps({"type": "error", "message": "处理超时，请重试"})

        except Exception as e:
            logger.error(f"Process error: {e}", exc_info=True)
            error_msg = self._format_error_message(str(e), agent_name)
            if output_format == "legacy":
                yield self.format_legacy_error(error_msg)
            else:
                yield json.dumps({"type": "error", "message": error_msg})

    async def _process_stream(
        self, 
        process: asyncio.subprocess.Process, 
        request: RequestModel,
        output_format: str = "raw"
    ) -> AsyncGenerator[str, None]:
        """处理子进程的流式输出"""
        line_count = 0
        tool_input_buffer: Dict[int, str] = {}
        
        debug_file = None
        if DEBUG_STREAM:
            try:
                debug_file = open(DEBUG_STREAM_FILE, "a", encoding="utf-8")
                debug_file.write(f"\n\n=== New Stream Session: {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            except Exception as e:
                logger.warning(f"Failed to open debug stream file: {e}")

        try:
            async for line in process.stdout:
                line_count += 1
                try:
                    line_str = line.decode("utf-8").strip()
                    if not line_str:
                        continue
                    
                    if debug_file:
                        debug_file.write(f"[{line_count}] {line_str}\n")
                        debug_file.flush()

                    # 原始JSON行模式
                    if output_format == "raw":
                        yield line_str
                        continue

                    # 易事厅格式处理
                    data = json.loads(line_str)
                    event_type = data.get("type")
                    
                    for sse in self._process_legacy_event(data, event_type, tool_input_buffer):
                        yield sse

                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON line #{line_count}: {line_str[:100]}...")
                except Exception as e:
                    logger.error(f"Error processing stream line #{line_count}: {e}", exc_info=True)
                    if output_format == "legacy":
                        yield self.format_legacy_sse(f"处理流事件时出错: {str(e)}", finished=False)

            logger.info(f"Stream processing completed, total lines: {line_count}")

            if process.stderr:
                stderr_data = await process.stderr.read()
                if stderr_data:
                    stderr_str = stderr_data.decode('utf-8', errors='ignore')[:1000]
                    logger.warning(f"CCR stderr: {stderr_str}")
                    if debug_file:
                        debug_file.write(f"\n=== STDERR ===\n{stderr_str}\n")
        finally:
            if debug_file:
                debug_file.write(f"\n=== Stream End: {line_count} lines ===\n")
                debug_file.close()

    def _process_legacy_event(self, data: Dict[str, Any], event_type: str, tool_input_buffer: Dict[int, str]) -> List[str]:
        """处理易事厅格式的事件"""
        results = []
        
        if event_type == "result":
            pass
        
        elif event_type == "stream_event":
            formatted_text = self._format_stream_event_legacy(data, tool_input_buffer)
            if formatted_text:
                results.append(self.format_legacy_sse(formatted_text, finished=False))
        
        elif event_type == "user":
            formatted_text = self._format_user_message_legacy(data)
            if formatted_text:
                results.append(self.format_legacy_sse(formatted_text, finished=False))
        
        return results

    def _format_stream_event_legacy(self, data: Dict[str, Any], tool_input_buffer: Dict[int, str]) -> str:
        """格式化 stream_event 类型的数据（易事厅格式）"""
        event = data.get("event", {})
        event_type = event.get("type")
        
        if event_type == "content_block_delta":
            delta = event.get("delta", {})
            delta_type = delta.get("type")
            
            if delta_type == "text_delta":
                text = delta.get("text", "")
                return self._sanitize_text(text)
            
            elif delta_type == "input_json_delta":
                index = event.get("index", 0)
                partial_json = delta.get("partial_json", "")
                if index not in tool_input_buffer:
                    tool_input_buffer[index] = ""
                tool_input_buffer[index] += partial_json
        
        elif event_type == "content_block_start":
            content_block = event.get("content_block", {})
            block_type = content_block.get("type")
            
            if block_type == "tool_use":
                tool_name = content_block.get("name", "unknown")
                return f"\n🔧 **调用工具: {tool_name}**\n"
        
        elif event_type == "content_block_stop":
            index = event.get("index", 0)
            if index in tool_input_buffer:
                params = tool_input_buffer.pop(index)
                if params:
                    try:
                        params_obj = json.loads(params)
                        if isinstance(params_obj, dict):
                            key_params = []
                            for key in ["command", "pattern", "path", "filePath", "content", "description"]:
                                if key in params_obj:
                                    val = params_obj[key]
                                    if isinstance(val, str) and len(val) > 100:
                                        val = val[:100] + "..."
                                    key_params.append(f"{key}: {val}")
                            if key_params:
                                return f"参数: {', '.join(key_params[:3])}\n"
                    except json.JSONDecodeError:
                        pass
        
        return ""

    def _format_user_message_legacy(self, data: Dict[str, Any]) -> str:
        """格式化 user 消息（工具结果）（易事厅格式）"""
        message = data.get("message", {})
        content = message.get("content", [])
        
        results = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_result":
                result_content = item.get("content", "")
                is_error = item.get("is_error", False)
                
                if isinstance(result_content, list):
                    text_parts = []
                    for rc in result_content:
                        if isinstance(rc, dict) and rc.get("type") == "text":
                            text_parts.append(rc.get("text", "")[:500])
                        elif isinstance(rc, str):
                            text_parts.append(rc[:500])
                    result_content = "\n".join(text_parts)
                elif isinstance(result_content, str):
                    result_content = result_content[:500]
                else:
                    result_content = str(result_content)[:500]
                
                if is_error:
                    results.append(f"❌ **错误**: {result_content}\n")
                else:
                    results.append(f"✅ **结果**: {result_content}\n")
        
        return "".join(results)

    def _clean_content(self, content: str) -> str:
        """清理输入内容"""
        triggers_to_remove = []
        cleaned = content
        
        for trigger in triggers_to_remove:
            if trigger in cleaned:
                cleaned = cleaned.replace(trigger, '')

        cleaned = cleaned.strip()
        while cleaned.startswith('\n'):
            cleaned = cleaned[1:].strip()

        return cleaned

    def _check_for_admin_command(self, content: str) -> bool:
        """检查是否包含管理员命令"""
        admin_commands = ["/clear"]
        return any(cmd in content for cmd in admin_commands)

    def _parse_model_param(self, content: str) -> tuple:
        """解析content中的--model参数"""
        model_pattern = r'--model\s+([^\s]+(?:\s*,\s*[^\s,]+)*)'
        match = re.search(model_pattern, content)
        
        if match:
            model_value = match.group(1).strip()
            cleaned_content = re.sub(model_pattern, '', content).strip()
            cleaned_content = re.sub(r'\s+', ' ', cleaned_content).strip()
            return cleaned_content, model_value
        
        return content, None

    def _build_command(self, agent_name: str, content: str) -> List[str]:
        """构建CCR命令"""
        cleaned_content, model_param = self._parse_model_param(content)
        ccr_command = self.config.agent_ccr_command_map.get(agent_name, self.config.ccr_command)
        
        cmd = [ccr_command]
        
        if ccr_command == "ccr":
            cmd.append("code")
        
        if cleaned_content.lower() == "/clear":
            cmd.extend(["-p"])
            message = "你好"
        else:
            cmd.extend(["-c", "-p"])
            message = cleaned_content
        
        cmd.extend([
            "--output-format", "stream-json",
            "--include-partial-messages",
            "--verbose",
        ])
        
        if model_param:
            cmd.extend(["--model", model_param])
        
        cmd.extend([message, "--dangerously-skip-permissions"])
        
        return cmd

    def _sanitize_text(self, text: str) -> str:
        """剔除文本中的<think>和</think>标签"""
        return re.sub(r'</?think>', '', text)

    def _format_error_message(self, error: str, agent_name: str) -> str:
        """格式化错误消息"""
        if "su:" in error:
            return f"无法切换到用户 '{agent_name}'。请确保用户存在且当前进程有切换权限。"
        elif "cannot create child process" in error.lower():
            return f"无法创建子进程。可能是权限不足或资源限制。"
        return f"处理错误: {error}"

    def format_legacy_sse(self, response: str, finished: bool = False, answer_success: int = 1) -> str:
        """格式化为易事厅 SSE 格式"""
        data = {
            "response": response,
            "finished": finished,
            "global_output": {
                "context": "",
                "answer_success": answer_success,
                "docs": [],
            },
        }
        json_data = json.dumps(data, ensure_ascii=False)
        return f"event:delta\ndata:{json_data}\n\n"

    def format_legacy_error(self, error_msg: str) -> str:
        """发送易事厅格式的错误消息"""
        return self.format_legacy_sse(error_msg, finished=True, answer_success=0)
