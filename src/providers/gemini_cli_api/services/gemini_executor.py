# -*- coding: utf-8 -*-
"""Gemini CLI executor

IMPORTANT:
- This module MUST NOT depend on `claude_code_api`.
- It keeps the same call surface used by `claude_code_api` (execute + legacy helpers),
  but implements the subprocess runner locally.

`StreamHandler` may still choose to route slash-commands to CCR regardless of provider.
"""

from __future__ import annotations

import asyncio
import json
import os
import pwd
import re
import shlex
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List

import logging

logger = logging.getLogger(__name__)


class GeminiExecutor:
    """Execute Gemini CLI with stream-json output."""

    def __init__(self, config: Any = None):
        # Config is injected by API layer; keep attribute-based access.
        self.config = config

    async def execute(
        self,
        request_model: Any,
        agent_name: str,
        output_format: str = "raw",
    ) -> AsyncGenerator[str, None]:
        """Run `gemini` CLI and yield stream output.

        Args:
            request_model: Pydantic model (legacy RequestModel) from API layer.
            agent_name: Linux system username.
            output_format: "raw" (JSON lines) or "legacy" (event:delta SSE strings).
        """

        start_time = time.time()

        # Best-effort normalize fields (we avoid importing RequestModel here).
        api_user = getattr(request_model, "user", None) or "anonymous"
        content = getattr(request_model, "content", "") or ""

        if not content:
            raise ValueError("Missing required field: content")

        cleaned_content = self._clean_content(content)

        # Resolve exec dir (compatible with current CCR behavior, but without API-layer helpers).
        session_id = getattr(request_model, "session_id", None) or "default"
        cwd_mode = getattr(request_model, "cwd_mode", "") or ""
        run_kind = getattr(request_model, "run_kind", "") or ""

        run_cwd = getattr(request_model, "cwd", None)
        exec_dir = None

        if cwd_mode == "inplace" and run_cwd:
            exec_dir = Path(str(run_cwd))
        else:
            # Prefer configured base, fall back to /home.
            base = getattr(self.config, "user_home_base", "/home") if self.config else "/home"
            preferred_dir = Path(str(base)) / str(agent_name) / "sessions" / str(session_id)

            current_user = pwd.getpwuid(os.getuid()).pw_name
            if current_user != agent_name and os.geteuid() != 0:
                # Non-root fallback to avoid `su` and missing-user failures in dev/test.
                exec_dir = Path.home() / str(agent_name) / "sessions" / str(session_id)
            else:
                exec_dir = preferred_dir

            exec_dir.mkdir(parents=True, exist_ok=True)

        if run_cwd:
            # Validate provided cwd
            if not exec_dir.exists() or not exec_dir.is_dir():
                raise ValueError(f"cwd 不存在或不是目录: {exec_dir}")

        cmd = self._build_command(agent_name=agent_name, content=cleaned_content)

        # Wrap with cd + su if needed (mirrors CCR behavior).
        current_user = pwd.getpwuid(os.getuid()).pw_name
        cmd_str = " ".join(shlex.quote(arg) for arg in cmd)
        full_cmd = f"cd {shlex.quote(str(exec_dir))} && {cmd_str}"

        if current_user == agent_name:
            final_cmd = ["bash", "-c", full_cmd]
        else:
            final_cmd = ["su", "-", agent_name, "-c", full_cmd]

        timeout_s = float(getattr(self.config, "ccr_timeout", 120) if self.config else 120)

        try:
            process = await asyncio.create_subprocess_exec(
                *final_cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=10 * 1024 * 1024,
            )

            async for output in self._process_stream(process, output_format=output_format):
                yield output

            await asyncio.wait_for(process.wait(), timeout=timeout_s)

        except asyncio.TimeoutError:
            try:
                process.kill()
            except Exception:
                pass
            if output_format == "legacy":
                yield self.format_legacy_error("处理超时，请重试")
            else:
                yield json.dumps({"type": "error", "message": "处理超时，请重试"})

        except Exception as e:
            logger.exception("Gemini process error")
            msg = f"处理错误: {e}"
            if output_format == "legacy":
                yield self.format_legacy_error(msg)
            else:
                yield json.dumps({"type": "error", "message": msg})

        finally:
            _ = start_time  # keep parity hook for future metrics

    async def _process_stream(
        self,
        process: asyncio.subprocess.Process,
        output_format: str = "raw",
    ) -> AsyncGenerator[str, None]:
        line_count = 0
        tool_input_buffer: Dict[int, str] = {}

        timeout_s = float(getattr(self.config, "ccr_timeout", 120) if self.config else 120)

        while True:
            try:
                line = await asyncio.wait_for(process.stdout.readline(), timeout=timeout_s)
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except Exception:
                    pass
                raise

            if not line:
                break

            line_count += 1
            try:
                line_str = line.decode("utf-8").strip()
                if not line_str:
                    continue

                if output_format == "raw":
                    yield line_str
                    continue

                data = json.loads(line_str)
                event_type = data.get("type")
                for sse in self._process_legacy_event(data, event_type, tool_input_buffer):
                    yield sse

            except json.JSONDecodeError:
                # ignore invalid lines
                continue
            except Exception:
                if output_format == "legacy":
                    yield self.format_legacy_sse("处理流事件时出错", finished=False, answer_success=0)

        # Best-effort stderr drain (do not fail)
        try:
            if process.stderr:
                stderr_data = await process.stderr.read()
                if asyncio.iscoroutine(stderr_data):
                    stderr_data = await stderr_data
                if isinstance(stderr_data, (bytes, bytearray)) and stderr_data:
                    _ = stderr_data[:1000]
        except Exception:
            pass

    def _build_command(self, agent_name: str, content: str) -> List[str]:
        cleaned_content, model_param = self._parse_model_param(content)
        gemini_command = getattr(self.config, "gemini_command", "gemini") if self.config else "gemini"

        cmd = [gemini_command, "-p", cleaned_content, "--output-format", "stream-json"]
        if model_param:
            cmd.extend(["--model", model_param])
        return cmd

    def _parse_model_param(self, content: str) -> tuple[str, str | None]:
        model_pattern = r"--model\s+([^\s]+(?:\s*,\s*[^\s,]+)*)"
        match = re.search(model_pattern, content)
        if match:
            model_value = match.group(1).strip()
            cleaned_content = re.sub(model_pattern, "", content).strip()
            cleaned_content = re.sub(r"\s+", " ", cleaned_content).strip()
            return cleaned_content, model_value
        return content, None

    def _clean_content(self, content: str) -> str:
        cleaned = (content or "").strip()
        while cleaned.startswith("\n"):
            cleaned = cleaned[1:].strip()
        return cleaned

    def format_legacy_sse(self, response: str, finished: bool = False, answer_success: int = 1) -> str:
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
        return self.format_legacy_sse(error_msg, finished=True, answer_success=0)

    def _process_legacy_event(self, data: Dict[str, Any], event_type: str, tool_input_buffer: Dict[int, str]):
        """Legacy-formatting for Gemini events.

        This logic is kept compatible with the previous implementation.
        """

        results = []

        if event_type == "message":
            if data.get("role") == "assistant":
                content = data.get("content", "")
                if content:
                    results.append(self.format_legacy_sse(content, finished=False, answer_success=1))

        elif event_type == "tool_use":
            tool_name = data.get("tool_name") or "unknown"
            params = data.get("parameters")
            text = f"\n🔧 **调用工具: {tool_name}**\n"
            if params:
                try:
                    params_str = json.dumps(params, ensure_ascii=False)
                except Exception:
                    params_str = str(params)
                text += f"参数: {params_str}\n"
            results.append(self.format_legacy_sse(text, finished=False, answer_success=1))

        elif event_type == "tool_result":
            status = (data.get("status") or "").lower()
            output = data.get("output")
            content = "" if output is None else str(output)
            if status and status != "success":
                results.append(self.format_legacy_sse(f"❌ **错误**: {content}\n", finished=False, answer_success=0))
            else:
                results.append(self.format_legacy_sse(f"✅ **结果**: {content}\n", finished=False, answer_success=1))

        elif event_type == "result" and data.get("subtype") == "slash_command":
            content = data.get("content") or ""
            if content:
                results.append(self.format_legacy_sse(content, finished=True, answer_success=1))

        elif event_type == "error":
            msg = data.get("message") or "Gemini CLI error"
            results.append(self.format_legacy_sse(msg, finished=True, answer_success=0))

        return results
