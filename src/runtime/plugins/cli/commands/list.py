# -*- coding: utf-8 -*-
"""
list 命令实现

列出已安装的插件（向后兼容旧 CLI）。
"""

import argparse
from pathlib import Path

from . import BaseCommand
from ..utils import EnvManager, Printer


class ListCommand(BaseCommand):
    """list 命令
    
    列出已安装的 Providers 和 Channels（向后兼容）。
    """
    
    name = "list"
    help = "列出已安装的插件"
    
    def __init__(self):
        self.printer = Printer()
        self.base_dir = Path.cwd()
        self.env_manager = EnvManager(base_dir=self.base_dir)
        self.config_dir = self.base_dir / "config"
    
    def run(self, args: argparse.Namespace) -> int:
        """执行 list 命令"""
        list_type = getattr(args, "type", "all")
        
        self.printer.header("已安装的插件")
        
        if list_type in ("provider", "all"):
            self._list_providers()
        
        if list_type in ("channel", "all"):
            self._list_channels()
        
        return 0
    
    def _list_providers(self) -> None:
        """列出已安装的 Providers"""
        self.printer.section("Providers")
        
        providers_dir = self.config_dir / "providers"
        
        if not providers_dir.exists():
            self.printer.print("  (无已安装的 Provider)")
            return
        
        # 使用 PluginInstaller 获取 Provider 列表
        try:
            from ...installer import PluginInstaller
            installer = PluginInstaller()
            providers = installer.list_installed_providers()
            
            if providers:
                for pv in providers:
                    status = "✅ 启用" if installer.is_enabled("provider", pv) else "⏸️  禁用"
                    self.printer.list_item(f"{pv} [{status}]")
            else:
                self.printer.print("  (无已安装的 Provider)")
        except ImportError:
            # 回退到直接读取文件
            yaml_files = list(providers_dir.glob("*.yaml"))
            if yaml_files:
                for f in yaml_files:
                    self.printer.list_item(f.stem)
            else:
                self.printer.print("  (无已安装的 Provider)")
    
    def _list_channels(self) -> None:
        """列出已配置的 Channels"""
        self.printer.section("Channels")
        
        env_vars = self.env_manager.load_env()
        
        channels = [
            ("Telegram", "TELEGRAM_BOT_TOKEN"),
            ("Slack", "SLACK_BOT_TOKEN"),
            ("Discord", "DISCORD_BOT_TOKEN"),
            ("WhatsApp", "WHATSAPP_BRIDGE_URL"),
            ("Signal", "SIGNAL_PHONE_NUMBER"),
        ]
        
        any_configured = False
        for name, key in channels:
            if env_vars.get(key):
                status = "✅ 已配置"
                self.printer.list_item(f"{name} [{status}]")
                any_configured = True
        
        if not any_configured:
            self.printer.print("  (无已配置的 Channel)")
            self.printer.print()
            self.printer.print("  提示: 使用 'anexus install channel <name>' 安装 Channel 依赖")
            self.printer.print("        然后在 .env 文件中配置相应的 Token")
