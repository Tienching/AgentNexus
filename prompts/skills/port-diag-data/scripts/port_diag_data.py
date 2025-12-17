#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Port Diagnosis Data Collection Script

该脚本用于调用 SCF API 对网络设备端口进行诊断数据采集。
"""

import json
import requests
import argparse
import sys
import os
import time
import hmac
import hashlib
import copy


def filter_diagnosis_data(data: dict, output_type: str) -> dict:
    """
    根据输出类型过滤诊断数据

    Args:
        data: 原始 API 响应数据
        output_type: 输出类型 (simple/normal/deep)

    Returns:
        过滤后的数据
    """
    if output_type == 'deep':
        # deep: 返回完整数据
        return data

    # 深拷贝以避免修改原始数据
    filtered = copy.deepcopy(data)

    try:
        if 'Data' in filtered:
            # 删除 FuncResult（冗余数据）
            if 'FuncResult' in filtered['Data']:
                del filtered['Data']['FuncResult']

            # 解析嵌套的 RetMsg（如果是字符串）
            if 'RetMsg' in filtered['Data']:
                ret_msg = filtered['Data']['RetMsg']
                if isinstance(ret_msg, str):
                    ret_msg = json.loads(ret_msg)
                    filtered['Data']['RetMsg'] = ret_msg

                # 获取 diagnosis_data
                diagnosis_data = ret_msg.get('Data', {}).get('diagnosis_data', {})

                if output_type == 'simple':
                    # simple: 只返回 port_mappings
                    if 'diagnosis_results' in diagnosis_data:
                        del diagnosis_data['diagnosis_results']

                elif output_type == 'normal':
                    # normal: 返回 port_mappings 和 diagnosis_results（排除 bcm_phy 和 hexdump_eeprom）
                    diagnosis_results = diagnosis_data.get('diagnosis_results', {})
                    for interface_name, interface_data in diagnosis_results.items():
                        if isinstance(interface_data, dict):
                            # 删除 bcm_phy 和 hexdump_eeprom
                            if 'bcm_phy' in interface_data:
                                del interface_data['bcm_phy']
                            if 'hexdump_eeprom' in interface_data:
                                del interface_data['hexdump_eeprom']

    except (json.JSONDecodeError, KeyError, TypeError) as e:
        # 如果解析失败，返回原始数据
        pass

    return filtered


def generate_auth_header(body_str: str, appkey: str, system_id: str) -> str:
    """
    生成 HMAC-SHA512 签名的 Authorization header

    Args:
        body_str: 请求体的 JSON 字符串
        appkey: 应用密钥（十六进制格式）
        system_id: 系统ID

    Returns:
        Authorization header 字符串
    """
    # 获取当前时间戳（秒）
    timestamp = int(time.time())

    # 构建签名内容: timestamp + body
    sign_content = f"{timestamp}{body_str}"

    # 将 appkey 从十六进制字符串转换为字节
    appkey_bytes = bytes.fromhex(appkey)

    # 使用 HMAC-SHA512 计算签名
    signature = hmac.new(
        appkey_bytes,
        sign_content.encode('utf-8'),
        hashlib.sha512
    ).hexdigest()

    # 构建 Authorization header
    auth_header = f"HMAC-SHA-512 Timestamp={timestamp},Signature={signature},SystemId={system_id}"

    return auth_header


def call_port_diagnosis(device: str, interface: str, business: str, operator: str,
                         mode: str, api_url: str, appkey: str, system_id: str) -> dict:
    """
    调用端口诊断 API

    Args:
        device: 设备IP地址或名称
        interface: 接口名称
        business: 业务标识
        operator: 操作者
        mode: 请求模式 (sync/async)
        api_url: API URL
        appkey: 应用密钥
        system_id: 系统ID

    Returns:
        API 响应的 JSON 对象
    """
    # 构建请求体
    payload = {
        "Action": "Scf",
        "CloudFunctionName": "tswitch",
        "CloudFunctionReqData": {
            "Module": "open_port_diagnosis_dump",
            "Method": "open_dump_port_diagnosis",
            "Data": {
                "device": device,
                "interface": interface,
                "business": business,
                "operator": operator
            }
        },
        "Method": "Invoke",
        "RequestMode": mode,
        "RequestEnvironment": "product",
        "SystemId": system_id
    }

    # 将请求体转换为 JSON 字符串
    body_str = json.dumps(payload)

    # 生成 Authorization header
    auth_header = generate_auth_header(body_str, appkey, system_id)

    # 构建请求头
    headers = {
        'Content-Type': 'application/json',
        'Authorization': auth_header
    }

    # 发送请求
    response = requests.post(api_url, headers=headers, data=body_str, timeout=120)

    return response


def main():
    # 解析命令行参数
    parser = argparse.ArgumentParser(
        description='Port Diagnosis Data Collection - 调用 SCF API 进行端口诊断数据采集'
    )
    parser.add_argument('--device', '-d', type=str, required=True,
                        help='设备IP地址或设备名称')
    parser.add_argument('--interface', '-i', type=str, required=True,
                        help='接口名称，如 Eth200GE128')
    parser.add_argument('--business', '-b', type=str, default='diag',
                        help='业务标识，默认为 diag')
    parser.add_argument('--operator', '-o', type=str, default='claude',
                        help='操作者名称，默认为 claude')
    parser.add_argument('--mode', '-m', type=str, default='sync',
                        choices=['sync', 'async'],
                        help='请求模式：sync（同步）或 async（异步），默认为 sync')
    parser.add_argument('--type', '-t', type=str, default='normal',
                        choices=['simple', 'normal', 'deep'],
                        help='输出类型：simple（仅port_mappings）、normal（排除bcm_phy和hexdump_eeprom）、deep（完整数据），默认为 normal')

    args = parser.parse_args()

    # 从环境变量获取配置
    api_url = os.getenv('SCF_URL')
    appkey = os.getenv('SCF_APPKEY')
    system_id = os.getenv('SCF_SYSTEM')

    # 检查必需的环境变量
    missing_vars = []
    if not api_url:
        missing_vars.append('SCF_URL')
    if not appkey:
        missing_vars.append('SCF_APPKEY')
    if not system_id:
        missing_vars.append('SCF_SYSTEM')

    if missing_vars:
        print(f"Error: Missing required environment variables: {', '.join(missing_vars)}")
        print("\nPlease set the following environment variables:")
        print("  SCF_URL    - SCF API service URL")
        print("  SCF_APPKEY - SCF API application key (hex format)")
        print("  SCF_SYSTEM - System ID")
        sys.exit(1)

    # 打印请求信息
    print("=" * 60)
    print("Port Diagnosis Data Collection")
    print("=" * 60)
    print(f"Device:    {args.device}")
    print(f"Interface: {args.interface}")
    print(f"Business:  {args.business}")
    print(f"Operator:  {args.operator}")
    print(f"Mode:      {args.mode}")
    print(f"Type:      {args.type}")
    print("-" * 60)
    print("Sending request...")
    print("-" * 60)

    try:
        # 调用 API
        response = call_port_diagnosis(
            device=args.device,
            interface=args.interface,
            business=args.business,
            operator=args.operator,
            mode=args.mode,
            api_url=api_url,
            appkey=appkey,
            system_id=system_id
        )

        # 检查响应状态
        print(f"HTTP Status: {response.status_code}")
        print("-" * 60)

        # 尝试解析 JSON 响应
        try:
            result = response.json()
            # 根据 type 参数过滤数据
            filtered_result = filter_diagnosis_data(result, args.type)
            print("Response:")
            print(json.dumps(filtered_result, indent=2, ensure_ascii=False))
        except json.JSONDecodeError:
            print("Response (raw):")
            print(response.text)

        print("=" * 60)

        # 如果状态码不是 2xx，返回非零退出码
        if not response.ok:
            sys.exit(1)

    except requests.exceptions.Timeout:
        print("Error: Request timed out")
        sys.exit(1)
    except requests.exceptions.ConnectionError as e:
        print(f"Error: Connection failed - {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
