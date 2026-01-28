# -*- coding: utf-8 -*-
"""Gemini CLI -> Legacy SSE adapter"""

import json
from typing import Any, Dict, Optional


class GeminiLegacyAdapter:
    """Convert Gemini CLI events to legacy SSE format"""

    def convert(self, event: Dict[str, Any]) -> Optional[str]:
        if not isinstance(event, dict):
            return None
        event_type = event.get("type")

        if event_type == "message":
            role = event.get("role")
            if role != "assistant":
                return None
            content = event.get("content", "")
            if content:
                return self.format_sse(content)
            return None

        if event_type == "tool_use":
            tool_name = event.get("tool_name") or "unknown"
            params = event.get("parameters")
            text = f"\n🔧 **调用工具: {tool_name}**\n"
            if params:
                try:
                    params_str = json.dumps(params, ensure_ascii=False)
                except Exception:
                    params_str = str(params)
                text += f"参数: {params_str}\n"
            return self.format_sse(text)

        if event_type == "tool_result":
            status = (event.get("status") or "").lower()
            output = event.get("output")
            content = "" if output is None else str(output)
            if status and status != "success":
                return self.format_sse(f"❌ **错误**: {content}\n", answer_success=0)
            return self.format_sse(f"✅ **结果**: {content}\n", answer_success=1)

        if event_type == "result" and event.get("subtype") == "slash_command":
            content = event.get("content") or ""
            if content:
                return self.format_sse(content, finished=True, answer_success=1)
            return None

        if event_type == "error":
            msg = event.get("message") or "Gemini CLI error"
            return self.format_sse(msg, finished=True, answer_success=0)

        return None

    def format_sse(self, response: str, finished: bool = False, answer_success: int = 1) -> str:
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
