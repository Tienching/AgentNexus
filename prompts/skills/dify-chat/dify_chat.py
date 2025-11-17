#!/usr/bin/env python3
"""
Dify Chat API Skill Implementation (requests版)
专门用于调用Dify API进行对话查询的技能，使用requests库实现
"""

import os
import json
import sys
from typing import Optional

import requests
import argparse


class DifyChatSkill:
    def __init__(self, api_url: str = None, api_key: str = None, default_user: str = None):
        # 配置优先级：显式参数 > 环境变量 > 默认值/config.json（由外部传入）
        self.api_url = api_url or os.getenv("DIFY_API_URL", "http://api.dify.woa.com/v1/chat-messages")
        self.api_key = api_key
        self.default_user = default_user or os.getenv("DIFY_DEFAULT_USER", "louiszcwang")
        self.session = requests.Session()

    def chat(self, query: str, user: Optional[str] = None, response_mode: str = "streaming") -> str:
        """
        发送查询到Dify API并获取回答

        Args:
            query: 用户查询的问题
            user: 用户标识，默认使用预设用户
            response_mode: "streaming" 或 "blocking"

        Returns:
            AI回答内容
        """
        if user is None:
            user = self.default_user

        if response_mode not in ("streaming", "blocking"):
            response_mode = "streaming"

        if response_mode == "streaming":
            return self._chat_streaming(query, user)
        else:
            return self._chat_blocking(query, user)

    def _common_headers(self, streaming: bool = False):
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }
        if streaming:
            headers['Accept'] = 'text/event-stream'
        return headers

    def _payload(self, query: str, user: str, response_mode: str):
        return {
            "inputs": {},
            "query": query,
            "response_mode": response_mode,
            "user": user,
        }

    def _chat_blocking(self, query: str, user: str) -> str:
        url = self.api_url
        headers = self._common_headers(streaming=False)
        payload = self._payload(query, user, response_mode="blocking")

        try:
            resp = self.session.post(url, headers=headers, json=payload, timeout=(5, 60))
        except requests.RequestException as e:
            return f"请求失败: {e}"

        if resp.status_code != 200:
            # 直接返回服务端错误信息帮助排查
            try:
                return f"HTTP {resp.status_code}: {resp.text.strip()}"
            except Exception:
                return f"HTTP {resp.status_code}: 无法读取响应"

        # 解析JSON
        try:
            data = resp.json()
        except ValueError:
            return "未收到有效JSON响应"

        if isinstance(data, dict):
            if 'answer' in data:
                return str(data['answer']).strip()
            for key in ("message", "content", "data"):
                if key in data and isinstance(data[key], str):
                    return data[key].strip()
        return "未收到有效响应"

    def _chat_streaming(self, query: str, user: str) -> str:
        url = self.api_url
        headers = self._common_headers(streaming=True)
        payload = self._payload(query, user, response_mode="streaming")

        try:
            resp = self.session.post(url, headers=headers, json=payload, stream=True, timeout=(5, 60))
        except requests.RequestException as e:
            return f"请求失败: {e}"

        if resp.status_code != 200:
            # 读取完整文本以便诊断
            try:
                return f"HTTP {resp.status_code}: {resp.text.strip()}"
            except Exception:
                return f"HTTP {resp.status_code}: 无法读取响应"

        # 如果不是SSE，也尝试按整块JSON解析
        content_type = resp.headers.get('Content-Type', '')
        if 'text/event-stream' not in content_type:
            try:
                text = resp.text
                data = json.loads(text)
                if isinstance(data, dict) and 'answer' in data:
                    return str(data['answer']).strip()
            except Exception:
                pass
            return "未收到有效响应"

        # SSE逐行解析
        full_answer = []
        try:
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                line = line.strip()
                if not line.startswith('data:'):
                    continue
                data_str = line[5:].lstrip()
                if data_str == '[DONE]':
                    break
                try:
                    chunk = json.loads(data_str)
                except ValueError:
                    continue
                # Dify SSE片段通常包含answer字段
                if isinstance(chunk, dict) and 'answer' in chunk:
                    ans = chunk.get('answer')
                    if isinstance(ans, str):
                        full_answer.append(ans)
        finally:
            resp.close()

        if full_answer:
            return ''.join(full_answer).strip()

        # 兜底：尝试将累积文本当作JSON
        try:
            text = resp.text
            data = json.loads(text)
            if isinstance(data, dict) and 'answer' in data:
                return str(data['answer']).strip()
        except Exception:
            pass
        return "未收到有效响应"


def load_config():
    """加载配置文件"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_file = os.path.join(script_dir, 'config.json')

    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"警告: 无法加载配置文件 {config_file}: {e}")
        return {}


def main():
    """命令行入口函数"""
    parser = argparse.ArgumentParser(description="Dify Chat Skill (requests)")
    parser.add_argument("query", help="你的问题，例如：'bgp怎么配'")
    parser.add_argument("mode", nargs="?", default="streaming", choices=["streaming", "blocking"], help="响应模式：streaming 或 blocking")
    parser.add_argument("--api-key", dest="api_key", default=None, help="覆盖使用的 Dify API Key")
    parser.add_argument("--url", dest="api_url", default=None, help="覆盖使用的 Dify API URL")
    parser.add_argument("--user", dest="user", default=None, help="覆盖使用的默认用户")
    parser.add_argument("--verbose", dest="verbose", action="store_true", help="打印调试信息（会掩码敏感内容）")
    args = parser.parse_args()

    query = args.query
    response_mode = args.mode

    # 加载配置
    config = load_config()

    # 明确优先级：CLI > ENV > config
    api_url = args.api_url or os.getenv('DIFY_API_URL') or config.get('api_url')
    api_key = args.api_key or os.getenv('DIFY_API_KEY') or config.get('api_key')
    default_user = args.user or os.getenv('DIFY_DEFAULT_USER') or config.get('default_user')

    def mask_token(t: Optional[str]) -> str:
        if not t:
            return "<未设置>"
        # 显示前6后4，中间掩码
        return (t[:6] + "***" + t[-4:]) if len(t) > 10 else "***"

    if args.verbose:
        print(f"使用URL: {api_url or '[默认http://api.dify.woa.com/v1/chat-messages]'}")
        print(f"使用User: {default_user or '[默认louiszcwang]'}")
        print(f"使用API Key: {mask_token(api_key)} (来源: {'CLI' if args.api_key else ('ENV' if os.getenv('DIFY_API_KEY') else ('CONFIG' if config.get('api_key') else 'DEFAULT'))})")

    skill = DifyChatSkill(
        api_url=api_url,
        api_key=api_key,
        default_user=default_user,
    )

    result = skill.chat(query, response_mode=response_mode)
    print(result)


if __name__ == "__main__":
    main()