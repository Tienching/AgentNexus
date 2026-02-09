# -*- coding: utf-8 -*-
"""
install 命令实现

安装 Channel 或 Provider 依赖。
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from . import BaseCommand
from ..utils import Printer


class InstallCommand(BaseCommand):
    """install 命令
    
    安装依赖：
    - install channel [telegram|slack|discord|all]: 安装 Channel 依赖
    - install provider [claude|gemini|codex]: 安装 Provider
    """
    
    name = "install"
    help = "安装依赖"
    
    # Channel 依赖映射
    CHANNEL_EXTRAS = {
        "telegram": "telegram",
        "slack": "slack",
        "discord": "discord",
        "whatsapp": "whatsapp",
        "signal": "signal",
        "all": "all-channels",
    }
    
    # Provider 配置
    AVAILABLE_PROVIDERS = ["claude", "gemini", "codex", "codebuddy"]
    
    def __init__(self):
        self.printer = Printer()
        self.base_dir = Path.cwd()
    
    def run(self, args: argparse.Namespace) -> int:
        """执行 install 命令"""
        install_type = getattr(args, "install_type", None)
        
        if not install_type:
            self.printer.print("请指定安装类型:")
            self.printer.list_item("vhsdk install channel <name>  - 安装消息渠道依赖")
            self.printer.list_item("vhsdk install provider <name> - 安装 Provider")
            return 1
        
        if install_type == "channel":
            return self._install_channel(args)
        elif install_type == "provider":
            return self._install_provider(args)
        else:
            self.printer.error(f"未知的安装类型: {install_type}")
            return 1
    
    def _install_channel(self, args: argparse.Namespace) -> int:
        """安装 Channel 依赖"""
        name = getattr(args, "name", None)
        
        if not name:
            self.printer.error("请指定 Channel 名称")
            self.printer.print(f"可用 Channels: {', '.join(self.CHANNEL_EXTRAS.keys())}")
            return 1
        
        if name not in self.CHANNEL_EXTRAS:
            self.printer.error(f"未知的 Channel: {name}")
            self.printer.print(f"可用 Channels: {', '.join(self.CHANNEL_EXTRAS.keys())}")
            return 1
        
        extra = self.CHANNEL_EXTRAS[name]
        
        self.printer.header(f"安装 Channel 依赖: {name}")
        
        # 检测包管理器
        package_manager = self._detect_package_manager()
        
        if package_manager == "uv":
            return self._install_with_uv(extra)
        else:
            return self._install_with_pip(extra)
    
    def _install_provider(self, args: argparse.Namespace) -> int:
        """安装 Provider"""
        name = getattr(args, "name", None)
        
        if not name:
            self.printer.error("请指定 Provider 名称")
            self.printer.print(f"可用 Providers: {', '.join(self.AVAILABLE_PROVIDERS)}")
            return 1
        
        self.printer.header(f"安装 Provider: {name}")
        
        # 使用现有的 PluginInstaller
        try:
            from ...installer import PluginInstaller
            
            installer = PluginInstaller()
            success = installer.install_provider(name)
            
            if success:
                self.printer.success(f"Provider '{name}' 安装成功！")
                config_path = installer.get_config_path("provider", name)
                self.printer.print(f"\n配置文件: {config_path}")
                return 0
            else:
                self.printer.error(f"Provider '{name}' 不存在或安装失败")
                self.printer.print(f"可用 Providers: {', '.join(installer.list_available_providers())}")
                return 1
                
        except ImportError:
            self.printer.error("无法加载 PluginInstaller")
            return 1
    
    def _detect_package_manager(self) -> str:
        """检测使用的包管理器
        
        Returns:
            'uv' 或 'pip'
        """
        # 检查是否在 uv 管理的虚拟环境中
        if (self.base_dir / "uv.lock").exists():
            # 检查 uv 是否可用
            try:
                result = subprocess.run(
                    ["uv", "--version"],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    return "uv"
            except FileNotFoundError:
                pass
        
        return "pip"
    
    def _install_with_uv(self, extra: str) -> int:
        """使用 uv 安装依赖
        
        Args:
            extra: 可选依赖名称
            
        Returns:
            退出码
        """
        self.printer.info(f"使用 uv 安装 [{extra}] 依赖...")
        
        cmd = ["uv", "pip", "install", "-e", f".[{extra}]"]
        
        self.printer.print(f"执行: {' '.join(cmd)}")
        self.printer.print()
        
        try:
            result = subprocess.run(
                cmd,
                cwd=self.base_dir,
            )
            
            if result.returncode == 0:
                self.printer.print()
                self.printer.success("安装完成！")
                self._show_next_steps(extra)
                return 0
            else:
                self.printer.error("安装失败")
                return result.returncode
                
        except FileNotFoundError:
            self.printer.error("uv 命令未找到，尝试使用 pip...")
            return self._install_with_pip(extra)
    
    def _install_with_pip(self, extra: str) -> int:
        """使用 pip 安装依赖
        
        Args:
            extra: 可选依赖名称
            
        Returns:
            退出码
        """
        self.printer.info(f"使用 pip 安装 [{extra}] 依赖...")
        
        cmd = [sys.executable, "-m", "pip", "install", "-e", f".[{extra}]"]
        
        self.printer.print(f"执行: {' '.join(cmd)}")
        self.printer.print()
        
        try:
            result = subprocess.run(
                cmd,
                cwd=self.base_dir,
            )
            
            if result.returncode == 0:
                self.printer.print()
                self.printer.success("安装完成！")
                self._show_next_steps(extra)
                return 0
            else:
                self.printer.error("安装失败")
                return result.returncode
                
        except Exception as e:
            self.printer.error(f"执行失败: {e}")
            return 1
    
    def _show_next_steps(self, extra: str) -> None:
        """显示下一步操作提示"""
        self.printer.print()
        self.printer.print("下一步操作:")
        
        channel_env_keys = {
            "telegram": "TELEGRAM_BOT_TOKEN",
            "slack": "SLACK_BOT_TOKEN 和 SLACK_APP_TOKEN",
            "discord": "DISCORD_BOT_TOKEN",
            "whatsapp": "WHATSAPP_BRIDGE_URL（可选 WHATSAPP_BRIDGE_AUTH_TOKEN / WHATSAPP_SESSION_NAME）",
            "signal": "SIGNAL_API_URL 和 SIGNAL_PHONE_NUMBER",
            "all-channels": "相应的 Channel Token",
        }
        
        if extra in channel_env_keys:
            env_key = channel_env_keys[extra]
            self.printer.list_item(f"在 .env 文件中配置 {env_key}")
        
        self.printer.list_item("运行 'vhsdk start' 启动服务")
        self.printer.list_item("运行 'vhsdk status' 查看 Channel 状态")
