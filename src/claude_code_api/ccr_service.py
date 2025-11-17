"""CCR Code 服务核心逻辑"""

import asyncio
import json
import shlex
import time
import re
from pathlib import Path
from typing import AsyncGenerator, List, Dict, Any
from .models import RequestModel, Document
from .config import settings
from .logger import get_logger

logger = get_logger(__name__)


class CCRCodeService:
    """CCR Code 服务封装"""

    def __init__(self, config=None):
        """
        初始化服务

        Args:
            config: 配置对象，默认使用全局配置
        """
        self.config = config or settings
        self.logger = logger

    async def process_request(self, request: RequestModel, agent_name: str) -> AsyncGenerator[str, None]:
        """
        处理请求并生成流式响应

        Args:
            request: 请求模型
            agent_name: Linux系统用户名，用于切换用户身份运行命令

        Yields:
            SSE格式的字符串
        """
        start_time = time.time()

        # 确保用户目录存在 - 使用 {user_home_base}/{agent_name}/{api_user} 结构
        # 用户名是必需的，用于隔离不同用户的工作环境
        if not request.user:
            self.logger.error(
                f"Missing required user parameter",
                extra={
                    "agent_name": agent_name,
                    "msg_id": request.msg_id,
                }
            )
            raise ValueError("用户名参数是必需的，请在请求中提供 'user' 字段")

        user_dir = await self._ensure_user_directory(agent_name, request.user)
        self.logger.info(
            f"Using user directory",
            extra={
                "api_user": request.user,
                "agent_name": agent_name,
                "user_dir": str(user_dir),
                "msg_id": request.msg_id,
            }
        )
        
        # 清理输入内容（移除 @ 触发指令等）
        cleaned_content = self._clean_content(request.content)

        
        # 构建命令
        cmd = self._build_command(agent_name, cleaned_content)

        # 使用 su 命令包装，切换到 agent_name 用户并切换到工作目录
        # 使用 shlex.quote 确保每个参数都被正确转义
        ccr_cmd_str = ' '.join(shlex.quote(arg) for arg in cmd)

        # 总是切换到用户目录执行命令，确保工作目录正确
        full_cmd = f"cd {shlex.quote(str(user_dir))} && {ccr_cmd_str}"
        cmd = ["su", "-", agent_name, "-c", full_cmd]
        self.logger.info(
            f"Wrapping command with su for agent {agent_name}",
            extra={
                "agent_name": agent_name,
                "api_user": request.user,
                "user_dir": str(user_dir) if user_dir else "none",
                "wrapped_command": " ".join(cmd)
            }
        )

        # 记录CCR处理开始
        self.logger.info(
            f"Starting CCR processing",
            extra={
                "process_type": "ccr_start",
                "api_user": request.user,
                "agent_name": agent_name,
                "msg_id": request.msg_id,
                "original_content_length": len(request.content),
                "cleaned_content_length": len(cleaned_content),
                "content_preview": cleaned_content[:100] if len(cleaned_content) > 100 else cleaned_content,
                "command": " ".join(cmd),
            }
        )

        try:
            # 创建子进程，设置工作目录
            kwargs = {
                "stdout": asyncio.subprocess.PIPE,
                "stderr": asyncio.subprocess.PIPE,
            }
            # 使用 su 时不需要设置 cwd，因为 su 命令中已包含 cd

            logger.info(f"Creating subprocess with command: {cmd[:4]}", extra={
                "kwargs": kwargs,
                "using_su": True
            })

            process = await asyncio.create_subprocess_exec(
                *cmd,
                **kwargs
            )

            # 处理流式输出
            async for sse_event in self._process_stream(process, request):
                yield sse_event

            # 等待进程结束
            await asyncio.wait_for(process.wait(), timeout=self.config.ccr_timeout)

            duration = time.time() - start_time
            self.logger.info(
                f"CCR processing completed successfully",
                extra={
                    "process_type": "ccr_complete",
                    "duration_ms": int(duration * 1000),
                    "user": request.user,
                    "msg_id": request.msg_id,
                }
            )

        except asyncio.TimeoutError:
            duration = time.time() - start_time
            self.logger.error(
                f"CCR command timeout",
                extra={
                    "process_type": "ccr_timeout",
                    "user": request.user,
                    "msg_id": request.msg_id,
                    "duration_ms": int(duration * 1000),
                    "timeout_seconds": self.config.ccr_timeout,
                }
            )
            # 输出错误信息
            yield self._format_sse(
                {
                    "response": "处理超时，请重试",
                    "finished": True,
                    "global_output": {"context": "", "answer_success": 0, "docs": []},
                }
            )
        except Exception as e:
            self.logger.error(f"Process error: {e}", exc_info=True)
 
            # 根据错误类型生成更友好的错误消息
            error_msg = str(e)
            if "su:" in error_msg:
                error_msg = f"无法切换到用户 '{agent_name}'。请确保用户存在且当前进程有切换权限。"
            elif "cannot create child process" in error_msg.lower():
                error_msg = f"无法创建子进程。可能是权限不足或资源限制。"
            else:
                error_msg = f"处理错误: {str(e)}"

            # 输出错误信息
            yield self._format_sse(
                {
                    "response": error_msg,
                    "finished": True,
                    "global_output": {"context": "", "answer_success": 0, "docs": []},
                }
            )

    async def _process_stream(
        self, process: asyncio.subprocess.Process, _request: RequestModel
    ) -> AsyncGenerator[str, None]:
        """
        处理子进程的流式输出

        Args:
            process: 子进程对象
            request: 请求对象

        Yields:
            SSE格式的事件
        """

        tool_input_buffer = {}  # 用于累积工具输入的JSON片段

        async for line in process.stdout:
            try:
                line_str = line.decode("utf-8").strip()
                if not line_str:
                    continue

                # 解析JSON行
                data = json.loads(line_str)
                event_type = data.get("type")

                # 处理result类型 - 最终结果（跳过，避免重复输出）
                if event_type == "result":
                    # 不发送最终结果，避免与流式输出重复
                    # 直接结束，不发送任何响应
                    break

                # 处理stream_event类型
                elif event_type == "stream_event":
                    formatted_text = self._format_stream_event(data, tool_input_buffer)
                    if formatted_text:
                        yield self._format_sse(
                            {
                                "response": formatted_text,
                                "finished": False,
                                "global_output": {
                                    "context": "",
                                    "answer_success": 0,
                                    "docs": [],
                                },
                            }
                        )

                # # 处理assistant类型
                # elif event_type == "assistant":
                #     formatted_text = self._format_assistant_message(data)
                #     if formatted_text:
                #         yield self._format_sse(
                #             {
                #                 "response": formatted_text,
                #                 "finished": False,
                #                 "global_output": {
                #                     "context": "",
                #                     "answer_success": 0,
                #                     "docs": [],
                #                 },
                #             }
                #         )

                # 处理user类型（工具结果）
                elif event_type == "user":
                    formatted_text = self._format_user_message(data)
                    if formatted_text:
                        yield self._format_sse(
                            {
                                "response": formatted_text,
                                "finished": False,
                                "global_output": {
                                    "context": "",
                                    "answer_success": 0,
                                    "docs": [],
                                },
                            }
                        )

            except json.JSONDecodeError as e:
                self.logger.warning(f"Invalid JSON line: {line_str[:100]}... Error: {e}")
                continue
            except Exception as e:
                self.logger.error(f"Error processing stream line: {e}", exc_info=True)
                continue

    
    def _check_for_admin_command(self, content: str) -> bool:
        """
        检查消息中是否包含管理员命令
        """
        admin_commands = [
            "/clear",
        ]
        return any(admin_command in content for admin_command in admin_commands)

    async def _ensure_user_directory(self, agent_name: str, api_user: str) -> Path:
        """
        确保用户目录存在，使用 {user_home_base}/{agent_name}/{api_user} 结构

        Args:
            agent_name: Linux系统用户名
            api_user: API用户名

        Returns:
            用户目录路径
        """
        # 使用配置中的 user_home_base 路径，默认为 /home
        user_dir = Path(self.config.user_home_base) / agent_name / api_user

        if not user_dir.exists():
            try:
                # 使用 su 命令切换到 agent_name 用户来创建目录
                # 这样目录会以 agent_name 用户的身份和权限创建
                mkdir_cmd = f"mkdir -p {shlex.quote(str(user_dir))}"
                cmd = ["su", "-", agent_name, "-c", mkdir_cmd]

                self.logger.info(
                    f"Creating user directory as agent user",
                    extra={
                        "agent_name": agent_name,
                        "api_user": api_user,
                        "user_dir": str(user_dir),
                        "command": " ".join(cmd),
                        "action": "create_dir"
                    }
                )

                # 执行命令
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )

                _, stderr = await process.communicate()

                if process.returncode != 0:
                    error_msg = stderr.decode('utf-8').strip() if stderr else "Unknown error"
                    self.logger.error(
                        f"Failed to create user directory via su",
                        extra={
                            "agent_name": agent_name,
                            "api_user": api_user,
                            "user_dir": str(user_dir),
                            "error": error_msg,
                            "returncode": process.returncode
                        }
                    )
                    raise RuntimeError(f"无法以 {agent_name} 用户身份创建目录 {user_dir}: {error_msg}")

                self.logger.info(
                    f"Successfully created user directory",
                    extra={
                        "agent_name": agent_name,
                        "api_user": api_user,
                        "user_dir": str(user_dir),
                        "action": "create_dir_success"
                    }
                )

            except Exception as e:
                self.logger.error(
                    f"Failed to create user directory",
                    extra={
                        "agent_name": agent_name,
                        "api_user": api_user,
                        "user_dir": str(user_dir),
                        "error": str(e)
                    },
                    exc_info=True
                )
                raise RuntimeError(f"无法创建用户目录 {user_dir}: {e}")
        else:
            self.logger.debug(
                f"User directory already exists",
                extra={
                    "agent_name": agent_name,
                    "api_user": api_user,
                    "user_dir": str(user_dir),
                    "action": "check_dir"
                }
            )

        return user_dir


    def _clean_content(self, content: str) -> str:
        """
        清理输入内容，移除特定的 @ 触发指令

        Args:
            content: 原始用户输入内容

        Returns:
            清理后的内容
        """
        # 定义需要移除的特定 @ 触发指令列表
        triggers_to_remove = []

        cleaned = content
        removed_count = 0

        # 逐个移除特定的触发指令
        for trigger in triggers_to_remove:
            if trigger in cleaned:
                removed_count += cleaned.count(trigger)
                cleaned = cleaned.replace(trigger, '')

        # 清理多余的空白
        cleaned = cleaned.strip()

        # 如果开头有多余的换行，清理掉
        while cleaned.startswith('\n'):
            cleaned = cleaned[1:].strip()

        if cleaned != content:
            self.logger.debug(
                f"Cleaned user content",
                extra={
                    "original_length": len(content),
                    "cleaned_length": len(cleaned),
                    "removed_chars": len(content) - len(cleaned),
                    "removed_triggers_count": removed_count
                }
            )

        return cleaned

    
    def _parse_model_param(self, content: str) -> tuple[str, str]:
        """
        解析content中的--model参数
        
        Args:
            content: 用户输入内容
            
        Returns:
            (清理后的content, model参数值或None)
        """
        import re
        
        # 匹配 --model 参数的正则表达式，支持多种格式
        model_pattern = r'--model\s+([^\s]+(?:\s*,\s*[^\s,]+)*)'
        match = re.search(model_pattern, content)
        
        if match:
            model_value = match.group(1).strip()
            # 从content中移除--model参数，保持其他内容的格式
            cleaned_content = re.sub(model_pattern, '', content).strip()
            # 清理多余的空白
            cleaned_content = re.sub(r'\s+', ' ', cleaned_content).strip()
            
            self.logger.info(
                f"Parsed model parameter from content",
                extra={
                    "model_value": model_value,
                    "original_length": len(content),
                    "cleaned_length": len(cleaned_content)
                }
            )
            
            return cleaned_content, model_value
        
        return content, None

    def _build_command(self, agent_name: str, content: str) -> List[str]:
        """
        构建CCR命令

        Args:
            agent_name: 智能体名称
            content: 用户输入内容

        Returns:
            命令参数列表
        """
        # 解析模型参数
        cleaned_content, model_param = self._parse_model_param(content)

        ccr_command = self.config.agent_ccr_command_map.get(agent_name, self.config.ccr_command)
        
        # 基础命令参数
        cmd = [ccr_command]
        
        # 如果是 ccr 命令，添加 code 子命令
        if ccr_command == "ccr":
            cmd.append("code")
        
        # 根据内容类型添加相应参数
        if cleaned_content.lower() == "/clear":
            # 清理对话历史
            cmd.extend(["-p"])
            message = "你好"
        else:
            # 普通对话
            cmd.extend(["-c", "-p"])
            message = cleaned_content
        
        # 添加通用参数
        cmd.extend([
            "--output-format", "stream-json",
            "--include-partial-messages",
            "--verbose",
        ])
        
        # 如果有模型参数，添加到命令中
        if model_param:
            cmd.extend(["--model", model_param])
        
        # 最后添加消息内容和工具参数(默认添加所有工具)
        cmd.extend([
            message,
            "--dangerously-skip-permissions"
            # "--allowedTools", "Bash(tshark *),Read,mcp__ip_resource_mcp__get_tencent_private_ip_info,mcp__ip_resource_mcp__get_public_ip_info",
        ])
        
        return cmd

    def _format_sse(self, data: Dict[str, Any]) -> str:
        """
        格式化为Server-Sent Events格式

        Args:
            data: 要发送的数据

        Returns:
            SSE格式的字符串
        """
        json_data = json.dumps(data, ensure_ascii=False)
        return f"event:delta\ndata:{json_data}\n\n"

    def _sanitize_text(self, text: str) -> str:
        """
        剔除文本中的<think>和</think>标签

        Args:
            text: 原始文本

        Returns:
            清理后的文本
        """
        # 使用正则表达式替换<think>和</think>标签
        text = re.sub(r'</?think>', '', text)
        return text

    def _format_stream_event(self, data: Dict[str, Any], tool_input_buffer: Dict[str, str]) -> str:
        """
        格式化stream_event类型的数据

        Args:
            data: 事件数据
            tool_input_buffer: 工具输入缓冲

        Returns:
            格式化后的文本
        """
        event = data.get("event", {})
        event_type = event.get("type")

        # 处理文本增量
        if event_type == "content_block_delta":
            delta = event.get("delta", {})
            delta_type = delta.get("type")

            if delta_type == "text_delta":
                text = delta.get("text", "")
                # 剔除<think>标签
                return self._sanitize_text(text)

            elif delta_type == "input_json_delta":
                # 累积JSON片段（工具参数）
                partial = delta.get("partial_json", "")
                # 获取当前工具ID
                tool_id = event.get("index", 0)
                if tool_id not in tool_input_buffer:
                    tool_input_buffer[tool_id] = ("未知", "")
                # 更新参数部分，保持工具名不变
                tool_name, existing_params = tool_input_buffer[tool_id]
                tool_input_buffer[tool_id] = (tool_name, existing_params + partial)
                return ""  # 累积中，不输出

        # 处理工具使用开始
        elif event_type == "content_block_start":
            content_block = event.get("content_block", {})
            if content_block.get("type") == "tool_use":
                tool_name = content_block.get("name", "未知")
                tool_id = content_block.get("id", "")
                # 获取工具的索引
                index = event.get("index", 0)
                # 初始化该工具的缓冲区，存储工具名和参数
                tool_input_buffer[index] = (tool_name, "")
                return ""  # 暂不输出，等待参数收集完成

        # 处理工具使用结束
        elif event_type == "content_block_stop":
            index = event.get("index", 0)
            if index in tool_input_buffer:
                # 获取工具名和累积的参数
                tool_name, params = tool_input_buffer[index]
                del tool_input_buffer[index]

                if not params:
                    return f"\n- 🛠️ [调用工具: {tool_name}]\n"

                try:
                    # 尝试解析JSON
                    params_obj = json.loads(params)
                    # 特殊处理todos，保持原有格式
                    if "todos" in params_obj:
                        todos_markdown = self._format_todos_markdown(params_obj['todos'])
                        return f"\n{todos_markdown}"
                    else:
                        # 其他工具统一使用text格式，单行显示
                        if "command" in params_obj:
                            return f"\n- 🛠️ [调用工具: {tool_name}] {params_obj['command']}"
                        elif "query" in params_obj:
                            return f"\n- 🛠️ [调用工具: {tool_name}] {params_obj['query']}"
                        else:
                            # 其他参数直接显示JSON字符串
                            return f"\n- 🛠️ [调用工具: {tool_name}] {params}"
                except:
                    # JSON解析失败，直接显示原始参数
                    return f"\n- 🛠️ [调用工具: {tool_name}] {params}"

        return ""

    def _format_assistant_message(self, data: Dict[str, Any]) -> str:
        """
        格式化assistant类型的消息

        Args:
            data: 消息数据

        Returns:
            格式化后的文本
        """
        message = data.get("message", {})
        content = message.get("content", [])

        # 确保content是列表
        if isinstance(content, str):
            # 如果是字符串，直接返回
            return self._sanitize_text(content)
        elif not isinstance(content, list):
            content = []

        formatted_parts = []
        for item in content:
            if item.get("type") == "text":
                text = item.get("text", "")
                # 剔除<think>标签
                text = self._sanitize_text(text)
                if text:
                    formatted_parts.append(text)
            elif item.get("type") == "tool_use":
                # 工具使用信息已在stream_event中处理
                pass

        return "".join(formatted_parts)

    def _format_user_message(self, data: Dict[str, Any]) -> str:
        """
        格式化user类型的消息（工具结果）

        Args:
            data: 消息数据

        Returns:
            格式化后的文本
        """
        message = data.get("message", {})
        content = message.get("content", [])

        # 确保content是列表
        if isinstance(content, str):
            # 如果是字符串，直接返回（例如/context命令的输出）
            return content
        elif not isinstance(content, list):
            content = []

        formatted_parts = []
        for item in content:
            if item.get("type") == "tool_result":
                is_error = item.get("is_error", False)
                content_text = item.get("content", "")

                # # 处理工具结果的智能截断
                # truncated_text = self._truncate_tool_result(content_text)

                if is_error:
                    formatted_parts.append(f"\n🚨 [工具错误]\n```text\n{content_text}\n```\n")
                else:
                    # formatted_parts.append(f"\n🗒️ [工具结果]\n```text\n{truncated_text}\n```\n")
                    formatted_parts.append(f" ⇨ [{len(content_text)} chars]\n")
                    pass

        return "".join(formatted_parts)

    def _format_todos_markdown(self, todos: List[Dict[str, Any]]) -> str:
        """
        将todos格式化为markdown格式

        Args:
            todos: todos列表

        Returns:
            markdown格式的todo列表
        """
        if not todos:
            return ""
        
        # 状态到markdown checkbox和emoji的映射
        status_mapping = {
            "completed": {"checkbox": "[x]", "emoji": "✅"},
            "in_progress": {"checkbox": "[ ]", "emoji": "🔄"}, 
            "pending": {"checkbox": "[ ]", "emoji": "⏳"},
            "cancelled": {"checkbox": "[ ]", "emoji": "❌"}
        }
        
        formatted_lines = ["### 📋 任务列表\n"]
        
        for todo in todos:
            content = todo.get("content", "")
            status = todo.get("status", "pending")
            # 忽略 activeForm 字段
            
            mapping = status_mapping.get(status, {"checkbox": "[ ]", "emoji": "⏳"})
            checkbox = mapping["checkbox"]
            emoji = mapping["emoji"]
            
            if status == "cancelled":
                formatted_lines.append(f"- {checkbox} {emoji} {content}")
            elif status == "in_progress":
                formatted_lines.append(f"- {checkbox} {emoji} **{content}** (进行中)")
            else:
                formatted_lines.append(f"- {checkbox} {emoji} {content}")
        
        formatted_lines.append("")  # 添加空行
        return "\n".join(formatted_lines)

    def _truncate_tool_result(self, content: str, max_lines: int = 3) -> str:
        """
        截断工具结果，保留前N行并添加简要概要

        Args:
            content: 原始内容
            max_lines: 保留的最大行数

        Returns:
            截断后的内容
        """
        if not content:
            return content

        lines = content.split('\n')
        total_lines = len(lines)

        # 如果行数不超过阈值的两倍，直接返回
        if total_lines <= max_lines * 2:
            return content

        # 保留前max_lines行
        kept_lines = lines[:max_lines]
        omitted_count = total_lines - max_lines

        # 组合结果
        result = '\n'.join(kept_lines)
        result += f"\n... (省略 {omitted_count} 行)"

        return result


    def _extract_result(self, data: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
        """
        从result类型数据中提取最终结果

        Args:
            data: result数据

        Returns:
            (最终文本, global_output)
        """
        result_text = data.get("result", "")
        is_error = data.get("is_error", False)

        # 剔除<think>标签
        result_text = self._sanitize_text(result_text)

        # 构建global_output
        global_output = {
            "context": "",
            "answer_success": 0 if is_error else 1,
            "docs": [],  # TODO: 从result中提取文档信息
        }

        return result_text, global_output

    async def extract_documents(self, text: str) -> List[Document]:
        """
        从文本中提取文档信息

        Args:
            text: 包含文档信息的文本

        Returns:
            文档列表
        """
        # 这里可以实现从CCR响应中提取文档的逻辑
        # 目前返回空列表
        return []
