#!/usr/bin/env python3
"""
设备诊断数据管理工具
支持创建任务、查询任务、下载任务以及一体化操作
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
from datetime import datetime, timezone
from typing import List, Dict, Optional, Union

# 宏定义常量
DEFAULT_TOOL_TYPE = "diag信息采集"
DEFAULT_OPERATOR = "jonaszchen"
DEFAULT_OUTPUT_PATH = "./"
DEFAULT_PAGE = 1
DEFAULT_LIMIT = 10
DEFAULT_STATUS = "成功"
DEFAULT_MAX_WAIT = 300


class DeviceDiagCollector:
    def __init__(self, username: str = None, secret: str = None):
        """
        初始化设备诊断采集器

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
                "或通过参数传递：DeviceDiagCollector(username='your_username', secret='your_secret')"
            )

        self.base_url = "http://operus.ngate.tencent-cloud.com/operus/operation/tools"
        self.session = requests.Session()
        self._initialize_cookies()

    def _initialize_cookies(self):
        """
        初始化cookie - 仅使用HMAC-SHA256认证，不依赖cookie
        """
        print("使用HMAC-SHA256认证方式，不依赖cookie")
        # 清除所有cookies，确保不使用硬编码cookie
        self.session.cookies.clear()

    def _fetch_cookies_dynamically(self):
        """
        已移除动态获取cookie逻辑，仅使用HMAC-SHA256认证
        """
        # 不再需要动态获取cookie，直接返回
        return

    def _test_cookie_validity(self) -> bool:
        """
        测试当前cookie是否有效，通过发送一个简单的请求

        Returns:
            bool: cookie是否有效
        """
        try:
            # 使用一个轻量级的请求来测试cookie
            test_url = f"{self.base_url}/queryTask"
            test_payload = {
                "pageNo": 1,
                "limit": 1,
                "toolType": "diag信息采集",
                "status": "成功",
                "devIpList": ["127.0.0.1"]  # 使用一个不存在的IP进行测试
            }

            body = json.dumps(test_payload)
            headers = self._generate_auth_headers(body)

            response = self.session.post(
                test_url,
                headers=headers,
                data=body,
                timeout=5
            )

            # 如果返回的JSON包含预期的字段，说明cookie有效
            result = response.json()
            if 'returnCode' in result and result['returnCode'] != 100001:
                return True

        except Exception:
            pass

        return False

    def _parse_and_set_cookies(self, cookie_str: str):
        """
        解析cookie字符串并设置到session中

        Args:
            cookie_str: cookie字符串，格式如 "name1=value1; name2=value2"
        """
        if not cookie_str:
            return

        # 清除现有cookies
        self.session.cookies.clear()

        # 解析并设置cookies
        for cookie in cookie_str.split(';'):
            if '=' in cookie:
                name, value = cookie.strip().split('=', 1)
                self.session.cookies.set(name.strip(), value.strip())

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

    def create_task(self,
                   dev_ip_list: Optional[List[str]] = None,
                   dev_name_list: Optional[List[str]] = None,
                   tool_type: str = "diag信息采集",
                   tool_params: Optional[Dict] = None,
                   operator: str = "jonaszchen") -> Dict:
        """
        创建诊断任务

        Args:
            dev_ip_list: 设备IP列表
            dev_name_list: 设备名称列表
            tool_type: 工具类型
            tool_params: 工具参数
            operator: 操作员

        Returns:
            创建任务的响应结果
        """
        if not dev_ip_list and not dev_name_list:
            raise ValueError("必须提供dev_ip_list或dev_name_list中的一个")

        if dev_ip_list and dev_name_list:
            raise ValueError("不能同时提供dev_ip_list和dev_name_list")

        payload = {
            "toolType": tool_type,
            "operator": operator
        }

        if dev_ip_list:
            payload["devIpList"] = dev_ip_list
        else:
            payload["devNameList"] = dev_name_list

        if tool_params:
            payload["toolParams"] = tool_params

        body = json.dumps(payload)
        headers = self._generate_auth_headers(body)

        try:
            # 调试信息
            print(f"请求URL: {self.base_url}/createTask")
            print(f"请求体: {body}")
            print(f"认证头: {json.dumps(headers, indent=2)}")
            print(f"Cookies: {dict(self.session.cookies)}")

            # 基于用户提供的工作代码，添加完整的请求头
            full_headers = headers.copy()
            full_headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'Origin': 'http://operus.ngate.tencent-cloud.com',
                'Referer': 'http://operus.ngate.tencent-cloud.com/',
                'Connection': 'keep-alive',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-origin'
            })

            print(f"完整请求头: {json.dumps(full_headers, indent=2)}")

            # 使用session发送请求
            print(f"发送创建任务请求到: {self.base_url}/createTask")
            response = self.session.post(
                f"{self.base_url}/createTask",
                headers=full_headers,
                data=body,
                timeout=30  # 添加超时
            )
            print(f"响应状态码: {response.status_code}")
            print(f"响应内容: {response.text[:500]}...")  # 只显示前500字符

            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            raise Exception("创建任务超时，请检查网络连接")
        except requests.exceptions.RequestException as e:
            raise Exception(f"创建任务失败: {str(e)}")

    def query_task(self,
                   dev_ip_list: Optional[List[str]] = None,
                   dev_name_list: Optional[List[str]] = None,
                   tool_type: str = "diag信息采集",
                   status: str = "成功",
                   page_no: int = 1,
                   limit: int = 1) -> Dict:
        """
        查询诊断任务

        Args:
            dev_ip_list: 设备IP列表
            dev_name_list: 设备名称列表
            tool_type: 工具类型
            status: 任务状态
            page_no: 页码
            limit: 每页限制数量

        Returns:
            查询任务的响应结果
        """
        if not dev_ip_list and not dev_name_list:
            raise ValueError("必须提供dev_ip_list或dev_name_list中的一个")

        if dev_ip_list and dev_name_list:
            raise ValueError("不能同时提供dev_ip_list和dev_name_list")

        payload = {
            "pageNo": page_no,
            "limit": limit,
            "toolType": tool_type,
            "status": status
        }

        if dev_ip_list:
            payload["devIpList"] = dev_ip_list
        else:
            payload["devNameList"] = dev_name_list

        body = json.dumps(payload)
        headers = self._generate_auth_headers(body)

        try:
            print(f"发送查询任务请求到: {self.base_url}/queryTask")
            response = self.session.post(
                f"{self.base_url}/queryTask",
                headers=headers,
                data=body,
                timeout=30  # 添加超时
            )
            print(f"查询响应状态码: {response.status_code}")
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            raise Exception("查询任务超时，请检查网络连接")
        except requests.exceptions.RequestException as e:
            raise Exception(f"查询任务失败: {str(e)}")

    def wait_for_task_completion(self,
                                 dev_ip_list: Optional[List[str]] = None,
                                 dev_name_list: Optional[List[str]] = None,
                                 tool_type: str = "diag信息采集",
                                 max_wait_time: int = DEFAULT_MAX_WAIT,
                                 poll_interval: int = 10,
                                 created_time: Optional[str] = None) -> Dict:
        """
        等待任务完成

        Args:
            dev_ip_list: 设备IP列表
            dev_name_list: 设备名称列表
            tool_type: 工具类型
            max_wait_time: 最大等待时间（秒）
            poll_interval: 轮询间隔（秒）
            created_time: 任务创建时间，用于识别新创建的任务

        Returns:
            完成任务的响应结果
        """
        start_time = time.time()

        while time.time() - start_time < max_wait_time:
            try:
                # 查询成功状态的任务
                result = self.query_task(
                    dev_ip_list=dev_ip_list,
                    dev_name_list=dev_name_list,
                    tool_type=tool_type,
                    status="成功"
                )

                # 查找新创建的已完成任务
                new_completed_task = self._find_new_task(result, created_time, status="成功")
                if new_completed_task:
                    print(f"新创建的任务完成！任务ID: {new_completed_task.get('taskId')}")
                    return result

                # 查询失败状态的任务
                failed_result = self.query_task(
                    dev_ip_list=dev_ip_list,
                    dev_name_list=dev_name_list,
                    tool_type=tool_type,
                    status="失败"
                )

                # 查找新创建的失败任务
                new_failed_task = self._find_new_task(failed_result, created_time, status="失败")
                if new_failed_task:
                    print(f"新创建的任务失败！任务ID: {new_failed_task.get('taskId')}")
                    return failed_result

                print(f"新创建的任务仍在进行中... ({int(time.time() - start_time)}s)")
                time.sleep(poll_interval)

            except Exception as e:
                print(f"查询任务状态时出错: {str(e)}")
                time.sleep(poll_interval)

        raise TimeoutError(f"等待任务完成超时，已等待 {max_wait_time} 秒")

    def _find_new_task(self, result: Dict, created_time: Optional[str], status: str) -> Optional[Dict]:
        """
        在查询结果中查找新创建的任务

        Args:
            result: 查询任务的结果
            created_time: 任务创建时间基准
            status: 任务状态

        Returns:
            找到的新任务，如果没有找到则返回None
        """
        if not created_time:
            # 如果没有提供创建时间，返回第一个任务（向后兼容）
            if result.get('data', {}).get('data') and len(result['data']['data']) > 0:
                return result['data']['data'][0]
            return None

        if not result.get('data', {}).get('data'):
            return None

        # 解析创建时间
        try:
            from datetime import datetime
            if created_time.endswith('Z'):
                # 处理 ISO 8601 格式（带Z后缀）
                created_dt = datetime.fromisoformat(created_time.replace('Z', '+00:00'))
            else:
                # 处理带时区偏移的格式
                created_dt = datetime.fromisoformat(created_time)
        except Exception as e:
            print(f"时间解析失败: {created_time}, 错误: {e}")
            # 如果时间解析失败，返回第一个任务
            if result['data']['data']:
                return result['data']['data'][0]
            return None

        # 查找创建时间晚于基准时间的任务
        for task in result['data']['data']:
            task_create_time = task.get('createTime')
            if task_create_time:
                try:
                    # 处理服务器返回的时间格式
                    if task_create_time.endswith('Z'):
                        task_dt = datetime.fromisoformat(task_create_time.replace('Z', '+00:00'))
                    else:
                        # 服务器返回的是北京时间，无时区信息，需要添加时区
                        task_dt = datetime.fromisoformat(task_create_time)
                        # 假设服务器时间是北京时间（UTC+8）
                        from datetime import timedelta
                        task_dt = task_dt.replace(tzinfo=created_dt.tzinfo) - timedelta(hours=8)

                    print(f"比较任务时间: {task_create_time} -> {task_dt} vs 基准时间: {created_dt}")

                    # 如果任务创建时间晚于或接近我们的基准时间，说明是新任务
                    # 使用大于等于比较，并允许1秒的时间误差
                    time_diff = (task_dt - created_dt).total_seconds()
                    if time_diff >= -1.0:  # 允许1秒的误差
                        print(f"找到新任务: {task.get('taskId')}, 时间差: {time_diff}秒")
                        return task
                except Exception as e:
                    print(f"任务时间解析失败: {task_create_time}, 错误: {e}")
                    # 如果时间解析失败，继续检查下一个任务
                    continue

        return None

    def download_result_file(self, result_url: str, local_path: str = "./") -> str:
        """
        下载结果文件

        Args:
            result_url: 结果文件URL
            local_path: 本地保存路径

        Returns:
            下载文件的完整路径
        """
        try:
            response = self.session.get(result_url, stream=True)
            response.raise_for_status()

            # 从URL中提取文件名，去除查询参数
            url_path = result_url.split('?')[0]  # 去除查询参数
            url_filename = url_path.split('/')[-1]  # 获取最后一个路径部分

            # 如果文件名包含URL编码，进行解码
            import urllib.parse
            try:
                decoded_filename = urllib.parse.unquote(url_filename)
                # 去除开头的斜杠（如果存在）
                if decoded_filename.startswith('/'):
                    decoded_filename = decoded_filename[1:]
            except:
                decoded_filename = url_filename

            # 如果文件名仍然太长或为空，生成一个合理的文件名
            if not decoded_filename or len(decoded_filename) > 100:
                # 尝试从原始URL中提取设备名和时间戳
                import re
                # 匹配设备名和时间戳模式
                match = re.search(r'([^/]+)\.(\d{8}_\d{6})\.tar', url_path)
                if match:
                    device_name = match.group(1).replace('%2F', '_')[:20]  # 限制长度
                    timestamp = match.group(2)
                    filename = f"{device_name}_{timestamp}.tar.gz"
                else:
                    # 使用时间戳生成文件名
                    filename = f"diag_result_{int(time.time())}.tar.gz"
            else:
                filename = decoded_filename

            # 确保本地目录存在
            os.makedirs(local_path, exist_ok=True)

            # 保存文件
            file_path = os.path.join(local_path, filename)
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            print(f"文件下载成功: {file_path}")
            return file_path

        except requests.exceptions.RequestException as e:
            raise Exception(f"下载文件失败: {str(e)}")

    def collect_diag_info(self,
                          devices: Union[List[str], str],
                          is_ip: bool = True,
                          tool_params: Optional[Dict] = None,
                          download_path: str = "./",
                          max_wait_time: int = DEFAULT_MAX_WAIT) -> str:
        """
        完整的诊断信息采集流程

        Args:
            devices: 设备列表（IP或名称）
            is_ip: 是否为IP地址（True为IP，False为设备名）
            tool_params: 工具参数
            download_path: 下载路径
            max_wait_time: 最大等待时间

        Returns:
            下载文件的完整路径
        """
        # 确保devices是列表格式
        if isinstance(devices, str):
            devices = [devices]

        try:
            # 1. 创建任务
            print("正在创建诊断任务...")
            create_result = self.create_task(
                dev_ip_list=devices if is_ip else None,
                dev_name_list=None if is_ip else devices,
                tool_params=tool_params
            )
            print(f"任务创建成功: {json.dumps(create_result, ensure_ascii=False, indent=2)}")

            # 2. 等待任务完成
            print("正在等待任务完成...")
            # 使用当前时间作为基准时间（UTC时间）
            from datetime import datetime, timezone
            current_time = datetime.now(timezone.utc).isoformat()
            print(f"基准时间（UTC）: {current_time}")
            task_result = self.wait_for_task_completion(
                dev_ip_list=devices if is_ip else None,
                dev_name_list=None if is_ip else devices,
                max_wait_time=max_wait_time,
                created_time=current_time
            )

            # 3. 提取结果URL
            if not task_result.get('data', {}).get('data') or len(task_result['data']['data']) == 0:
                raise Exception("未找到完成的任务结果")

            completed_task = task_result['data']['data'][0]
            result_url = completed_task.get('resultFileUrl')

            if not result_url:
                raise Exception("任务结果中未找到下载链接")

            print(f"任务完成，结果URL: {result_url}")

            # 4. 下载文件
            downloaded_file = self.download_result_file(result_url, download_path)

            print(f"诊断信息采集完成！文件保存在: {downloaded_file}")
            return downloaded_file

        except Exception as e:
            error_msg = f"诊断信息采集失败: {str(e)}"
            print(error_msg)
            raise Exception(error_msg)


def parse_devices(devices_str: str) -> List[str]:
    """解析设备列表字符串"""
    if not devices_str:
        return []
    return [device.strip() for device in devices_str.split(',') if device.strip()]


def parse_tool_params(params_str: str) -> Dict:
    """解析工具参数字符串"""
    if not params_str:
        return {}
    try:
        return json.loads(params_str)
    except json.JSONDecodeError:
        print(f"错误: 工具参数格式不正确: {params_str}")
        print("示例: '{\"key1\":\"value1\", \"key2\":\"value2\"}'")
        sys.exit(1)


def cmd_create(args):
    """创建任务命令"""
    print("=== 创建诊断任务 ===")

    devices = parse_devices(args.devices)
    if not devices:
        print("错误: 必须提供设备列表")
        sys.exit(1)

    tool_params = parse_tool_params(args.tool_params) if args.tool_params else {}

    collector = DeviceDiagCollector()

    try:
        # 如果没有提供tool_params，使用默认的参数
        if not tool_params:
            tool_params = {
                "key1": "value1",
                "key2": "value2"
            }

        result = collector.create_task(
            dev_ip_list=devices if args.is_ip else None,
            dev_name_list=None if args.is_ip else devices,
            tool_type=DEFAULT_TOOL_TYPE,
            tool_params=tool_params,
            operator=DEFAULT_OPERATOR
        )

        print(f"任务创建成功!")
        print(json.dumps(result, ensure_ascii=False, indent=2))

        # 保存任务ID到文件，方便后续操作
        if result.get('data', {}).get('taskId'):
            task_id_file = f"task_id_{result['data']['taskId']}.txt"
            with open(task_id_file, 'w') as f:
                f.write(result['data']['taskId'])
            print(f"任务ID已保存到: {task_id_file}")

    except Exception as e:
        print(f"创建任务失败: {str(e)}")
        sys.exit(1)


def cmd_query(args):
    """查询任务命令"""
    print("=== 查询诊断任务 ===")

    devices = parse_devices(args.devices)
    if not devices:
        print("错误: 必须提供设备列表")
        sys.exit(1)

    collector = DeviceDiagCollector()

    try:
        result = collector.query_task(
            dev_ip_list=devices if args.is_ip else None,
            dev_name_list=None if args.is_ip else devices,
            tool_type=DEFAULT_TOOL_TYPE,
            status=DEFAULT_STATUS,
            page_no=DEFAULT_PAGE,
            limit=DEFAULT_LIMIT
        )

        print(f"查询结果:")
        print(json.dumps(result, ensure_ascii=False, indent=2))

        # 如果有结果，显示任务状态
        if result.get('data', {}).get('data'):
            for task in result['data']['data']:
                print(f"\n任务ID: {task.get('taskId', 'N/A')}")
                print(f"设备: {task.get('devIp', task.get('devName', 'N/A'))}")
                print(f"状态: {task.get('status', 'N/A')}")
                print(f"创建时间: {task.get('createTime', 'N/A')}")
                if task.get('resultFileUrl'):
                    print(f"结果URL: {task.get('resultFileUrl')}")
        else:
            print("未找到匹配的任务")

    except Exception as e:
        print(f"查询任务失败: {str(e)}")
        sys.exit(1)


def cmd_download(args):
    """下载任务命令"""
    print("=== 下载诊断文件 ===")

    if not args.url:
        print("错误: 必须提供结果文件URL")
        sys.exit(1)

    collector = DeviceDiagCollector()

    try:
        downloaded_file = collector.download_result_file(args.url, DEFAULT_OUTPUT_PATH)
        print(f"文件下载成功: {downloaded_file}")

    except Exception as e:
        print(f"下载文件失败: {str(e)}")
        sys.exit(1)


def cmd_all(args):
    """一体化操作命令"""
    print("=== 一体化诊断数据采集 ===")

    devices = parse_devices(args.devices)
    if not devices:
        print("错误: 必须提供设备列表")
        sys.exit(1)

    tool_params = parse_tool_params(args.tool_params) if args.tool_params else {}

    # 如果没有提供tool_params，使用默认的参数
    if not tool_params:
        tool_params = {
            "key1": "value1",
            "key2": "value2"
        }

    collector = DeviceDiagCollector()

    try:
        downloaded_file = collector.collect_diag_info(
            devices=devices,
            is_ip=args.is_ip,
            tool_params=tool_params,
            download_path=DEFAULT_OUTPUT_PATH,
            max_wait_time=DEFAULT_MAX_WAIT
        )

        print(f"诊断数据采集完成!")
        print(f"结果文件: {downloaded_file}")

    except Exception as e:
        print(f"一体化操作失败: {str(e)}")
        sys.exit(1)


def main():
    """主函数，解析命令行参数并执行相应功能"""
    parser = argparse.ArgumentParser(
        description="设备诊断数据管理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 创建任务
  python device_diag_manager.py create -d "29.159.248.25" --ip

  # 查询任务
  python device_diag_manager.py query -d "29.159.248.25" --ip

  # 下载文件
  python device_diag_manager.py download -u "http://operus.ngate.tencent-cloud.com/operus/operation/tools/download/file.tar.gz"

  # 一体化操作
  python device_diag_manager.py all -d "29.159.248.25" --ip
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='可用命令', required=True)

    # 创建任务命令
    parser_create = subparsers.add_parser('create', help='创建诊断任务')
    parser_create.add_argument('-d', '--devices', required=True,
                              help='设备列表，用逗号分隔 (例如: "29.159.248.25,29.159.248.26")')
    parser_create.add_argument('--ip', action='store_true', dest='is_ip',
                              help='设备列表为IP地址 (默认为设备名称)')
    parser_create.add_argument('--tool-params',
                              help='工具参数JSON字符串 (例如: \'{"key1":"value1"}\')')
    parser_create.set_defaults(func=cmd_create)

    # 查询任务命令
    parser_query = subparsers.add_parser('query', help='查询诊断任务')
    parser_query.add_argument('-d', '--devices', required=True,
                             help='设备列表，用逗号分隔')
    parser_query.add_argument('--ip', action='store_true', dest='is_ip',
                             help='设备列表为IP地址 (默认为设备名称)')
    parser_query.set_defaults(func=cmd_query)

    # 下载文件命令
    parser_download = subparsers.add_parser('download', help='下载诊断文件')
    parser_download.add_argument('-u', '--url', required=True,
                                help='结果文件URL')
    parser_download.set_defaults(func=cmd_download)

    # 一体化操作命令
    parser_all = subparsers.add_parser('all', help='创建查询下载一体化操作')
    parser_all.add_argument('-d', '--devices', required=True,
                           help='设备列表，用逗号分隔')
    parser_all.add_argument('--ip', action='store_true', dest='is_ip',
                           help='设备列表为IP地址 (默认为设备名称)')
    parser_all.add_argument('--tool-params',
                           help='工具参数JSON字符串')
    parser_all.set_defaults(func=cmd_all)

    # 解析参数
    args = parser.parse_args()

    # 执行对应命令
    args.func(args)


if __name__ == "__main__":
    main()