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
        """微信个人号扫码登录已在精简版中移除。"""
        self.printer.print()
        self.printer.warning("当前精简版已移除消息渠道登录流程。")
        self.printer.list_item("如需继续精简，请改用 Provider / Settings 主流程完成配置")
        self.printer.list_item("如需保留旧微信扫码能力，请从历史版本恢复对应 channel 模块")
        self.printer.print()
        return 1

    @staticmethod
    def _mask_token(token: str) -> str:
        """遮盖 Token 中间部分"""
        if len(token) <= 8:
            return "****"
        return token[:4] + "****" + token[-4:]
