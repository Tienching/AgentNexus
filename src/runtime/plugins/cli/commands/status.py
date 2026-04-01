# -*- coding: utf-8 -*-
"""
status 命令实现

显示服务运行状态和配置信息。
"""

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from . import BaseCommand
from ..utils import ProcessManager, EnvManager, Printer


class StatusCommand(BaseCommand):
    """status 命令
    
    显示服务状态：
    - 服务运行状态（PID、内存、运行时长）
    - 当前配置信息
    - 已启用的 Channels 和 Providers
    - 健康检查
    """
    
    name = "status"
    help = "查看服务状态"
    
    # 敏感配置项（不显示值）
    SENSITIVE_KEYS = {
        "TELEGRAM_BOT_TOKEN",
        "SLACK_BOT_TOKEN",
        "SLACK_APP_TOKEN",
        "DISCORD_BOT_TOKEN",
        "WHATSAPP_BRIDGE_AUTH_TOKEN",
        "REDIS_PASSWORD",
    }
    
    def __init__(self):
        self.printer = Printer()
        self.base_dir = Path.cwd()
        self.process_manager = ProcessManager(base_dir=self.base_dir)
        self.env_manager = EnvManager(base_dir=self.base_dir)
    
    def run(self, args: argparse.Namespace) -> int:
        """执行 status 命令"""
        # JSON 输出模式
        if args.json:
            return self._output_json(args)
        
        # 常规输出
        self.printer.header("Agent Nexus 状态")
        
        # 1. 服务状态
        self._show_service_status()
        
        # 2. 配置信息（详细模式）
        if args.verbose:
            self._show_config()
        
        # 3. Channels 状态
        self._show_channels()
        
        # 4. 健康检查
        if args.health:
            self._show_health_check()
        
        return 0
    
    def _output_json(self, args: argparse.Namespace) -> int:
        """输出 JSON 格式状态"""
        status = self._collect_status(include_health=args.health)
        print(json.dumps(status, indent=2, default=str))
        return 0
    
    def _collect_status(self, include_health: bool = False) -> Dict[str, Any]:
        """收集所有状态信息
        
        Args:
            include_health: 是否包含健康检查
            
        Returns:
            状态字典
        """
        status: Dict[str, Any] = {
            "service": self._get_service_status(),
            "config": self._get_config_status(),
            "channels": self._get_channels_status(),
        }
        
        if include_health:
            status["health"] = self._get_health_status()
        
        return status
    
    def _get_service_status(self) -> Dict[str, Any]:
        """获取服务状态"""
        pid = self.process_manager.get_pid()
        running = self.process_manager.is_running()
        
        status = {
            "running": running,
            "pid": pid,
        }
        
        if running and pid:
            info = self.process_manager.get_process_info(pid)
            if info:
                status.update({
                    "memory_mb": info.get("memory_mb"),
                    "status": info.get("status"),
                    "uptime": self._calculate_uptime(info.get("create_time")),
                })
        
        return status
    
    def _calculate_uptime(self, create_time: Optional[float]) -> Optional[str]:
        """计算运行时长"""
        if create_time is None:
            return None
        
        elapsed = time.time() - create_time
        
        days = int(elapsed // 86400)
        hours = int((elapsed % 86400) // 3600)
        minutes = int((elapsed % 3600) // 60)
        seconds = int(elapsed % 60)
        
        parts = []
        if days > 0:
            parts.append(f"{days}天")
        if hours > 0:
            parts.append(f"{hours}小时")
        if minutes > 0:
            parts.append(f"{minutes}分钟")
        if seconds > 0 or not parts:
            parts.append(f"{seconds}秒")
        
        return " ".join(parts)
    
    def _get_config_status(self) -> Dict[str, Any]:
        """获取配置状态"""
        env_vars = self.env_manager.load_env()
        
        return {
            "env_file_exists": self.env_manager.exists(),
            "api_host": env_vars.get("API_HOST", "0.0.0.0"),
            "api_port": env_vars.get("API_PORT", "8081"),
            "environment": env_vars.get("ENVIRONMENT", "development"),
            "log_level": env_vars.get("LOG_LEVEL", "INFO"),
        }
    
    def _get_channels_status(self) -> Dict[str, bool]:
        """获取 Channels 配置状态"""
        env_vars = self.env_manager.load_env()
        
        channels = {
            "telegram": bool(env_vars.get("TELEGRAM_BOT_TOKEN")),
            "slack": bool(env_vars.get("SLACK_BOT_TOKEN")),
            "discord": bool(env_vars.get("DISCORD_BOT_TOKEN")),
            "feishu": bool(env_vars.get("FEISHU_APP_ID")),
            "whatsapp": bool(env_vars.get("WHATSAPP_BRIDGE_URL")),
            "signal": bool(env_vars.get("SIGNAL_PHONE_NUMBER")),
            "wechat": bool(env_vars.get("WECHAT_BOT_TOKEN")),
            "wecom": bool(env_vars.get("WECOM_TOKEN")),
            "wecom_bot": bool(env_vars.get("WECOM_BOT_TOKEN")),
        }
        
        return channels
    
    def _get_health_status(self) -> Dict[str, Any]:
        """获取健康检查状态"""
        env_vars = self.env_manager.load_env()
        host = env_vars.get("API_HOST", "127.0.0.1")
        port = env_vars.get("API_PORT", "8081")

        if host == "0.0.0.0":
            host = "127.0.0.1"

        url = f"http://{host}:{port}/health"

        try:
            import urllib.error
            import urllib.request

            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                raw_body = resp.read().decode("utf-8", errors="replace")
                if not raw_body:
                    return {
                        "status": "error",
                        "error": f"Health endpoint returned HTTP {resp.status} without a response body.",
                        "url": url,
                        "code": resp.status,
                        "checks": [
                            {
                                "name": "Health Endpoint",
                                "status": "error",
                                "message": f"Health endpoint returned HTTP {resp.status} without a response body.",
                                "detail": {
                                    "hint": "Inspect the server logs and verify the health endpoint still returns structured JSON.",
                                },
                            }
                        ],
                    }

                try:
                    payload = json.loads(raw_body)
                except json.JSONDecodeError:
                    return {
                        "status": "error",
                        "error": f"Health endpoint returned invalid JSON (HTTP {resp.status}).",
                        "url": url,
                        "code": resp.status,
                        "checks": [
                            {
                                "name": "Health Endpoint",
                                "status": "error",
                                "message": f"Health endpoint returned invalid JSON (HTTP {resp.status}).",
                                "detail": {
                                    "hint": "Inspect the server logs and verify the health endpoint still returns structured JSON.",
                                },
                            }
                        ],
                    }

                if not isinstance(payload, dict):
                    return {
                        "status": "error",
                        "error": f"Health endpoint returned an unexpected payload type: {type(payload).__name__}.",
                        "url": url,
                        "code": resp.status,
                        "checks": [
                            {
                                "name": "Health Endpoint",
                                "status": "error",
                                "message": f"Health endpoint returned an unexpected payload type: {type(payload).__name__}.",
                                "detail": {
                                    "hint": "Inspect the server logs and verify the health endpoint still returns structured JSON.",
                                },
                            }
                        ],
                    }

                payload["url"] = url
                payload["code"] = resp.status
                payload.setdefault("checks", [])
                payload.setdefault("status", "healthy")
                return payload
        except urllib.error.HTTPError as exc:
            raw_body = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw_body) if raw_body else {}
            except json.JSONDecodeError:
                payload = {}

            if not isinstance(payload, dict):
                payload = {}

            status = "error" if exc.code >= 500 else "unhealthy"
            payload["url"] = url
            payload["code"] = exc.code
            payload["status"] = payload.get("status") or status
            if payload["status"] == "healthy":
                payload["status"] = status
            payload.setdefault("error", f"Health endpoint returned HTTP {exc.code}.")
            payload.setdefault(
                "checks",
                [
                    {
                        "name": "Health Endpoint",
                        "status": status,
                        "message": payload["error"],
                        "detail": {
                            "hint": "Inspect the server logs and verify runtime dependencies before retrying.",
                        },
                    }
                ],
            )
            return payload
        except urllib.error.URLError as exc:
            message = f"Unable to reach health endpoint: {exc.reason}"
            return {
                "status": "unhealthy",
                "error": message,
                "url": url,
                "checks": [
                    {
                        "name": "Health Endpoint",
                        "status": "unhealthy",
                        "message": message,
                        "detail": {
                            "hint": "Ensure the API server is running and that API_HOST/API_PORT point to a reachable instance.",
                        },
                    }
                ],
            }
        except Exception as exc:
            message = f"Health check request failed: {exc}"
            return {
                "status": "error",
                "error": message,
                "url": url,
                "checks": [
                    {
                        "name": "Health Endpoint",
                        "status": "error",
                        "message": message,
                        "detail": {
                            "hint": "Inspect the local CLI environment and server logs for request failures.",
                        },
                    }
                ],
            }
    
    def _show_service_status(self) -> None:
        """显示服务状态"""
        self.printer.section("服务状态")
        
        status = self._get_service_status()
        
        if status["running"]:
            self.printer.success("服务运行中", prefix=False)
            self.printer.key_value("  PID", status["pid"])
            
            if status.get("memory_mb"):
                self.printer.key_value("  内存使用", f"{status['memory_mb']:.1f} MB")
            
            if status.get("uptime"):
                self.printer.key_value("  运行时长", status["uptime"])
            
            if status.get("status"):
                self.printer.key_value("  进程状态", status["status"])
        else:
            self.printer.warning("服务未运行", prefix=False)
            if status["pid"]:
                self.printer.print(f"  (存在过期的 PID 文件: {status['pid']})")
    
    def _show_config(self) -> None:
        """显示配置信息"""
        self.printer.section("配置信息")
        
        config = self._get_config_status()
        
        self.printer.key_value("配置文件", "存在" if config["env_file_exists"] else "不存在")
        self.printer.key_value("监听地址", f"{config['api_host']}:{config['api_port']}")
        self.printer.key_value("运行环境", config["environment"])
        self.printer.key_value("日志级别", config["log_level"])
    
    def _show_channels(self) -> None:
        """显示 Channels 状态"""
        self.printer.section("消息渠道")
        
        channels = self._get_channels_status()
        
        rows = []
        for name, configured in channels.items():
            status = "✅ 已配置" if configured else "⏸️  未配置"
            rows.append([name.capitalize(), status])
        
        self.printer.table(["渠道", "状态"], rows)
    
    def _show_health_check(self) -> None:
        """显示健康检查结果"""
        self.printer.section("健康检查")
        
        if not self._get_service_status()["running"]:
            self.printer.warning("服务未运行，跳过健康检查")
            return
        
        self.printer.info("正在检查服务健康状态...")
        
        health = self._get_health_status()
        overall_status = health.get("status", "unknown")
        checks = health.get("checks") or []
        code = health.get("code")

        summary = f"服务健康 ({overall_status}"
        if code is not None:
            summary += f", HTTP {code}"
        summary += ")"

        if overall_status == "healthy":
            self.printer.success(summary)
        elif overall_status in {"warning", "degraded"}:
            self.printer.warning(summary)
        else:
            self.printer.error(summary)

        self.printer.key_value("检查地址", health["url"])

        if health.get("error"):
            self.printer.key_value("错误摘要", health["error"])

        for check in checks:
            if not isinstance(check, dict):
                continue
            name = check.get("name", "Unknown")
            status = check.get("status", "unknown")
            message = check.get("message") or "无详细信息"
            detail = check.get("detail")

            self.printer.key_value(f"检查项 {name}", f"[{status}] {message}")
            if isinstance(detail, dict) and detail.get("hint"):
                self.printer.key_value("建议", detail["hint"], indent=1)
