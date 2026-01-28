# -*- coding: utf-8 -*-
"""
Plugins 层

CLI 安装器和插件管理。
"""

from .cli import main as cli_main
from .installer import PluginInstaller

__all__ = ["cli_main", "PluginInstaller"]
