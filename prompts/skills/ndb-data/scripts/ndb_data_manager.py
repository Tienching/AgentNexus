#!/usr/bin/env python3
"""
NDB设备devid查询工具
支持通过设备名称或IP地址查询设备的唯一标识符
"""

import argparse
import json
import sys
import os
import requests
import hashlib
import hmac
import base64
import time
import re
from datetime import datetime, timezone
from typing import List, Dict, Optional, Union

# 宏定义常量
DEFAULT_OUTPUT_FORMAT = "json"
DEFAULT_TIMEOUT = 30


class NDBDataCollector:
    def __init__(self, username: str = None, secret: str = None):
        """
        初始化NDB数据采集器

        Args:
            username: 用户名（可选，优先从环境变量读取）
            secret: 密钥（可选，优先从环境变量读取）
        """
        # 优先从环境变量读取认证信息
        self.username = username or os.environ.get('HMAC_USERNAME')
        self.secret = secret or os.environ.get('HMAC_SECRET')

        # 检查认证信息是否配置
        if not self.username or not self.secret:
            raise ValueError(
                "认证信息未配置！请设置环境变量：\n"
                "export HMAC_USERNAME='your_username'\n"
                "export HMAC_SECRET='your_secret'\n"
                "或通过参数传递：NDBDataCollector(username='your_username', secret='your_secret')"
            )

        self.base_url = "http://ndb.ngate.tencent-cloud.com/config/network/device"
        self.session = requests.Session()
        self.session.timeout = DEFAULT_TIMEOUT

    def _is_ip_address(self, device: str) -> bool:
        """
        判断设备标识是否为IP地址

        Args:
            device: 设备标识字符串

        Returns:
            bool: 是否为IP地址
        """
        # 简单的IP地址正则匹配
        ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
        return bool(re.match(ip_pattern, device.strip()))

    def _generate_auth_headers(self, body: str) -> Dict[str, str]:
        """
        生成认证头信息

        Args:
            body: 请求体内容

        Returns:
            包含认证信息的headers字典
        """
        # 生成GMT时间
        gmt_time = datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S GMT')

        # 计算SHA256摘要
        sha256_hash = hashlib.sha256(body.encode('utf-8')).digest()
        digest = f"SHA-256={base64.b64encode(sha256_hash).decode('utf-8')}"

        # 生成HMAC-SHA256签名
        sign_string = f"date: {gmt_time}\ndigest: {digest}"
        hmac_hash = hmac.new(
            self.secret.encode('utf-8'),
            sign_string.encode('utf-8'),
            hashlib.sha256
        ).digest()
        signature = base64.b64encode(hmac_hash).decode('utf-8')

        # 构建Authorization头
        authorization = f'hmac username="{self.username}", algorithm="hmac-sha256", headers="date digest", signature="{signature}"'

        return {
            'Content-Type': 'application/json',
            'Date': gmt_time,
            'Authorization': authorization,
            'Digest': digest
        }

    def query_device_devid(self,
                          devices: List[str],
                          force_ip: bool = False,
                          result_columns: List[str] = None) -> Dict:
        """
        查询设备devid

        Args:
            devices: 设备列表（设备名称或IP地址）
            force_ip: 强制将设备列表视为IP地址
            result_columns: 需要返回的结果列，默认为["id"]

        Returns:
            查询响应结果
        """
        if not devices:
            raise ValueError("设备列表不能为空")

        # 设置默认的结果列
        if result_columns is None:
            result_columns = ["id", "type", "levelName", "manageIp"]

        # 构建请求payload
        payload = {
            "devNames": devices,
            "resultColumn": result_columns
        }

        # 如果强制使用IP模式，转换设备名称格式
        if force_ip:
            # NDB API可能需要不同的字段名来处理IP查询
            # 这里先保持使用devNames，如果API不支持IP查询，可以后续调整
            pass

        # 发送请求
        url = f"{self.base_url}/get_device_info"
        body = json.dumps(payload)
        headers = self._generate_auth_headers(body)

        try:
            response = self.session.post(
                url,
                headers=headers,
                data=body
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"请求NDB API失败: {str(e)}")

    def format_output(self,
                     api_response: Dict,
                     devices: List[str],
                     output_format: str = "json") -> Union[str, Dict]:
        """
        格式化输出结果

        Args:
            api_response: NDB API响应
            devices: 查询的设备列表
            output_format: 输出格式（json或table）

        Returns:
            格式化后的结果
        """
        # 解析API响应
        success = api_response.get('success', False)
        return_code = api_response.get('returnCode', -1)
        data = api_response.get('data', [])
        trace_id = api_response.get('traceId', '')

        # 构建设备结果列表
        device_results = []

        if success and return_code == 0 and data:
            # API返回成功，解析设备信息
            for i, device in enumerate(devices):
                if i < len(data):
                    device_info = data[i]
                    device_id = device_info.get('id')
                    device_type = device_info.get('type')
                    level_name = device_info.get('levelName')
                    manage_ip = device_info.get('manageIp')

                    device_results.append({
                        'device': device,
                        'id': device_id,
                        'type': device_type,
                        'levelName': level_name,
                        'manageIp': manage_ip,
                        'status': 'found' if device_id is not None else 'not_found'
                    })
                else:
                    device_results.append({
                        'device': device,
                        'id': None,
                        'type': None,
                        'levelName': None,
                        'manageIp': None,
                        'status': 'not_found'
                    })
        else:
            # API返回失败，所有设备都标记为未找到
            for device in devices:
                device_results.append({
                    'device': device,
                    'id': None,
                    'type': None,
                    'levelName': None,
                    'manageIp': None,
                    'status': 'error'
                })

        # 构建完整结果
        result = {
            'success': success and return_code == 0,
            'devices': device_results,
            'total': len(devices),
            'traceId': trace_id,
            'returnCode': return_code,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        if output_format.lower() == 'table':
            # 生成表格格式输出
            if not device_results:
                return "没有查询到设备信息"

            # 表格头部
            header = f"{'设备名称':<40} {'设备ID':<10} {'类型':<8} {'角色':<15} {'管理IP':<15} {'状态':<10}"
            if trace_id:
                header += f" {'TraceId':<20}"
            lines = [header, "=" * len(header)]

            # 表格内容
            for device_result in device_results:
                manage_ip = device_result.get('manageIp') or 'N/A'
                device_type = device_result.get('type') or 'N/A'
                level_name = device_result.get('levelName') or 'N/A'
                line = f"{device_result['device']:<40} {str(device_result['id'] or 'N/A'):<10} {device_type:<8} {level_name:<15} {manage_ip:<15} {device_result['status']:<10}"
                if trace_id:
                    line += f" {trace_id:<20}"
                lines.append(line)

            return "\n".join(lines)
        else:
            # 返回JSON格式
            return result

    def save_to_file(self, data: Union[Dict, str], filename: str):
        """
        保存结果到文件

        Args:
            data: 要保存的数据
            filename: 文件名
        """
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                if isinstance(data, dict):
                    json.dump(data, f, ensure_ascii=False, indent=2)
                else:
                    f.write(data)
            print(f"结果已保存到: {filename}")
        except Exception as e:
            print(f"保存文件失败: {str(e)}")


def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='NDB设备devid查询工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 通过设备名称查询
  python ndb_data_manager.py -d "BJ-TX201-C03U05-IP49050-TCS9500-LC-159"

  # 通过IP地址查询
  python ndb_data_manager.py -d "29.159.248.25" --ip

  # 批量查询
  python ndb_data_manager.py -d "device1,device2,device3"

  # 保存结果到文件
  python ndb_data_manager.py -d "switch01" --save-to-file result.json
        """
    )

    parser.add_argument(
        '-d', '--devices',
        required=True,
        help='设备列表，用逗号分隔（设备名称或IP地址）'
    )

    parser.add_argument(
        '--ip',
        action='store_true',
        help='强制将设备列表视为IP地址格式'
    )

    parser.add_argument(
        '--output',
        choices=['json', 'table'],
        default='json',
        help='输出格式（默认: json）'
    )

    parser.add_argument(
        '--save-to-file',
        help='将结果保存到指定文件'
    )

    parser.add_argument(
        '--debug',
        action='store_true',
        help='启用调试模式，显示详细日志'
    )

    return parser.parse_args()


def main():
    """主函数"""
    try:
        # 解析命令行参数
        args = parse_arguments()

        # 设置调试模式
        if args.debug:
            print(f"调试模式已启用")
            print(f"查询设备: {args.devices}")
            print(f"强制IP模式: {args.ip}")
            print(f"输出格式: {args.output}")

        # 解析设备列表
        devices = [device.strip() for device in args.devices.split(',') if device.strip()]

        if not devices:
            print("错误: 设备列表为空")
            sys.exit(1)

        # 创建NDB数据采集器
        collector = NDBDataCollector()

        if args.debug:
            print(f"正在查询 {len(devices)} 个设备的devid...")

        # 查询设备devid
        api_response = collector.query_device_devid(devices, force_ip=args.ip)

        if args.debug:
            print(f"API响应: {json.dumps(api_response, ensure_ascii=False, indent=2)}")

        # 格式化输出结果
        formatted_result = collector.format_output(
            api_response,
            devices,
            output_format=args.output
        )

        # 输出结果
        if args.output.lower() == 'json':
            print(json.dumps(formatted_result, ensure_ascii=False, indent=2))
        else:
            print(formatted_result)

        # 保存到文件（如果指定）
        if args.save_to_file:
            collector.save_to_file(formatted_result, args.save_to_file)

        # 检查查询结果
        if isinstance(formatted_result, dict):
            success_count = sum(1 for d in formatted_result['devices'] if d['status'] == 'found')
            total_count = formatted_result['total']

            if success_count == 0:
                print(f"警告: 未找到任何设备的devid", file=sys.stderr)
                sys.exit(1)
            elif success_count < total_count:
                print(f"警告: 仅找到 {success_count}/{total_count} 个设备的devid", file=sys.stderr)

    except Exception as e:
        print(f"错误: {str(e)}", file=sys.stderr)
        if args.debug if 'args' in locals() else False:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()