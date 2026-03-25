# -*- coding: utf-8 -*-
"""
login 命令实现

支持通过扫码等方式获取各平台的 Bot Token，并自动保存到 .env。
目前支持:
  - wechat: 微信个人号扫码登录 (iLink Bot API)
"""

import argparse
import json
from pathlib import Path
from typing import Optional

from . import BaseCommand
from ..utils import EnvManager, Printer


class LoginCommand(BaseCommand):
    """login 命令

    通过扫码等方式获取 Bot Token 并保存到 .env。

    用法:
      anexus login wechat          # 微信个人号扫码登录
      anexus login wechat --base-url https://custom.api.com
    """

    name = "login"
    help = "登录消息渠道 — 通过扫码等方式获取 Bot Token"

    def __init__(self):
        self.printer = Printer()
        self.base_dir = Path.cwd()
        self.env_manager = EnvManager(base_dir=self.base_dir)

    def run(self, args: argparse.Namespace) -> int:
        """执行 login 命令"""
        platform = getattr(args, "platform", None)

        if not platform:
            self.printer.print()
            self.printer.info("请指定要登录的平台:")
            self.printer.list_item("anexus login wechat  — 微信个人号扫码登录")
            self.printer.print()
            return 1

        if platform == "wechat":
            return self._login_wechat(args)

        self.printer.error(f"未知平台: {platform}")
        return 1

    def _login_wechat(self, args: argparse.Namespace) -> int:
        """微信个人号 QR 扫码登录"""
        try:
            from channels.wechat_login import (
                LoginError,
                LoginTimeoutError,
                QRCodeExpiredError,
                WeChatQRLogin,
            )
        except ImportError:
            self.printer.error("无法导入微信登录模块，请确认安装完整")
            return 1

        # ── Banner ──
        self.printer.print()
        self.printer.print(self.printer._colorize(
            "╔══════════════════════════════════════════════════════╗", "cyan"))
        self.printer.print(self.printer._colorize(
            "║                                                      ║", "cyan"))
        self.printer.print(self.printer._colorize(
            "║       💬  微信个人号 — 扫码登录                  ║", "cyan"))
        self.printer.print(self.printer._colorize(
            "║                                                      ║", "cyan"))
        self.printer.print(self.printer._colorize(
            "║   请使用微信扫描二维码，完成登录后                    ║", "cyan"))
        self.printer.print(self.printer._colorize(
            "║   Bot Token 将自动保存到 .env 文件                   ║", "cyan"))
        self.printer.print(self.printer._colorize(
            "║                                                      ║", "cyan"))
        self.printer.print(self.printer._colorize(
            "╚══════════════════════════════════════════════════════╝", "cyan"))
        self.printer.print()

        # ── 确认 ──
        if not self.printer.confirm("是否开始扫码登录？", default=True):
            self.printer.info("已取消")
            return 2

        # ── 准备 ──
        base_url = getattr(args, "base_url", None)
        kwargs = {}
        if base_url:
            kwargs["base_url"] = base_url

        login_client = WeChatQRLogin(**kwargs)

        # ── 回调 ──
        def on_qr(qr_text: str) -> None:
            """QR 码展示回调"""
            self.printer.print()
            self.printer.print(qr_text)
            self.printer.print()

        def on_status(status: str, message: str) -> None:
            """状态变化回调"""
            status_icons = {
                "fetching_qr": "🔄",
                "wait": "⏳",
                "scaned": "📱",
                "confirmed": "✅",
                "expired": "⏰",
                "success": "🎉",
            }
            icon = status_icons.get(status, "ℹ️")
            self.printer.print(f"  {icon} {message}")

        # ── 执行登录 ──
        try:
            result = login_client.login(on_qr=on_qr, on_status=on_status)
        except LoginTimeoutError as e:
            self.printer.print()
            self.printer.error(str(e))
            return 1
        except QRCodeExpiredError as e:
            self.printer.print()
            self.printer.error(str(e))
            return 1
        except LoginError as e:
            self.printer.print()
            self.printer.error(f"登录失败: {e}")
            return 1
        except KeyboardInterrupt:
            self.printer.print()
            self.printer.warning("登录已取消")
            return 2
        except Exception as e:
            self.printer.print()
            self.printer.error(f"未知错误: {e}")
            return 1

        # ── 保存 Token ──
        self.printer.print()
        self.printer.section("保存配置")

        # 保存到 .env
        self.env_manager.set_value("WECHAT_BOT_TOKEN", result.bot_token)
        self.printer.success("WECHAT_BOT_TOKEN 已保存到 .env")

        # 如果 API 返回了不同的 base_url，也保存
        if result.base_url and result.base_url != "https://ilinkai.weixin.qq.com":
            self.env_manager.set_value("WECHAT_BASE_URL", result.base_url)
            self.printer.success(f"WECHAT_BASE_URL 已保存: {result.base_url}")

        # 确保 CHANNELS_ENABLED=true
        self.env_manager.set_value("CHANNELS_ENABLED", "true")

        # ── 完成摘要 ──
        self.printer.print()
        self.printer.print(self.printer._colorize(
            "╔══════════════════════════════════════════════════════╗", "green"))
        self.printer.print(self.printer._colorize(
            "║           🎉  微信登录成功！                         ║", "green"))
        self.printer.print(self.printer._colorize(
            "╚══════════════════════════════════════════════════════╝", "green"))
        self.printer.print()

        # 显示账号信息
        self.printer.key_value("用户 ID", result.ilink_user_id or "(未知)")
        self.printer.key_value("Bot ID", result.ilink_bot_id or "(未知)")
        self.printer.key_value("Token", self._mask_token(result.bot_token))
        self.printer.key_value("Base URL", result.base_url or "https://ilinkai.weixin.qq.com")

        self.printer.print()
        self.printer.print(self.printer._colorize("下一步操作:", "bold"))
        self.printer.list_item("运行 'anexus start' 启动服务")
        self.printer.list_item("运行 'anexus status' 查看 Channel 状态")
        self.printer.print()

        return 0

    @staticmethod
    def _mask_token(token: str) -> str:
        """遮盖 Token 中间部分"""
        if len(token) <= 8:
            return "****"
        return token[:4] + "****" + token[-4:]
