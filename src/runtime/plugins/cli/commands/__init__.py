# -*- coding: utf-8 -*-
"""
CLI 命令模块

提供所有 CLI 子命令的实现。
"""

import argparse
from abc import ABC, abstractmethod
from typing import Optional


class BaseCommand(ABC):
    """命令基类
    
    所有命令都应继承此类并实现 run 方法。
    """
    
    name: str = ""
    help: str = ""
    
    @abstractmethod
    def run(self, args: argparse.Namespace) -> int:
        """执行命令
        
        Args:
            args: 解析后的命令行参数
            
        Returns:
            退出码：0=成功，1=错误，2=用户中断
        """
        pass


# 延迟导入以避免循环依赖
def _lazy_import():
    from .init import InitCommand
    from .start import StartCommand
    from .stop import StopCommand
    from .status import StatusCommand
    from .config import ConfigCommand
    from .install import InstallCommand
    from .list import ListCommand
    from .onboard import OnboardCommand
    return InitCommand, StartCommand, StopCommand, StatusCommand, ConfigCommand, InstallCommand, ListCommand, OnboardCommand


# 导出命令类
InitCommand: type
StartCommand: type
StopCommand: type
StatusCommand: type
ConfigCommand: type
InstallCommand: type
ListCommand: type
OnboardCommand: type


def __getattr__(name: str):
    """延迟加载命令类"""
    commands = {
        "InitCommand": 0,
        "StartCommand": 1,
        "StopCommand": 2,
        "StatusCommand": 3,
        "ConfigCommand": 4,
        "InstallCommand": 5,
        "ListCommand": 6,
        "OnboardCommand": 7,
    }
    if name in commands:
        classes = _lazy_import()
        return classes[commands[name]]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BaseCommand",
    "InitCommand",
    "StartCommand",
    "StopCommand",
    "StatusCommand",
    "ConfigCommand",
    "InstallCommand",
    "ListCommand",
    "OnboardCommand",
]
