import json
import requests
import argparse
import sys
import os

def main():
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='Chat with Knot API')
    parser.add_argument('--message', '-m', type=str, required=True, help='The message/question to send')
    parser.add_argument('--conversation-id', '-c', type=str, default='', help='Conversation ID for maintaining chat history')
    parser.add_argument('--model', type=str, default='glm-4.6',
                       help='Model name (deepseek-r1-0528, deepseek-v3, kimi-k2-instruct, glm-4.6)')
    parser.add_argument('--stream', type=bool, default=True, help='Enable streaming response (true/false)')
    parser.add_argument('--web-search', type=bool, default=False, help='Enable web search (true/false)')

    args = parser.parse_args()

    # 从环境变量获取配置
    api_url = os.getenv('KNOT_URL')
    knot_token = os.getenv('KNOT_TOKEN')
    username = os.getenv('KNOT_NAME')

    # 检查必需的环境变量
    if not api_url:
        print("Error: KNOT_URL environment variable is not set")
        sys.exit(1)

    if not knot_token:
        print("Error: KNOT_TOKEN environment variable is not set")
        sys.exit(1)

    if not username:
        print("Error: KNOT_NAME environment variable is not set")
        sys.exit(1)

    # 如果没有提供消息但需要交互式输入，可以添加这个功能
    if not args.message:
        print("Please provide a message using --message or -m parameter")
        sys.exit(1)

    chat_body = {
        "input": {
            "message": args.message,
            "conversation_id": args.conversation_id,
            "model": args.model,
            "stream": args.stream,
            "enable_web_search": args.web_search
        }
    }

    headers = {
        "x-knot-token": knot_token,
        "X-Username": username
    }

    print(f"Sending message: {args.message}")
    print("-" * 50)

    response = requests.post(api_url, json=chat_body, headers=headers, stream=True)
    conversation_id = ""
    for chunk in response.iter_lines():
        if not chunk:
            continue
        chunk_str = chunk.decode("utf-8").lstrip("data:").strip()  # 处理数据块格式
        if chunk_str == "[DONE]":
            break
        msg = json.loads(chunk_str)
        if "type" in msg:
            msg_type = msg["type"]
            conversation_id = msg["rawEvent"]["conversation_id"]

            if msg_type == "TEXT_MESSAGE_CONTENT":
                print(msg["rawEvent"]["content"], end="")

    print("")
    print("-" * 50)
    print("conversation_id:", conversation_id) # 这个conversation_id设置到chat_body中的input.conversation_id，则会继承前面会话的历史记录

if __name__ == "__main__":
    main()
