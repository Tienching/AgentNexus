# -*- coding: utf-8 -*-
"""
init 命令实现

初始化项目配置文件和目录结构。
"""

import argparse
from pathlib import Path
from typing import Dict, Any

from . import BaseCommand
from ..utils import EnvManager, Printer


class InitCommand(BaseCommand):
    """init 命令
    
    初始化项目配置：
    - 从 .env.example 创建 .env 文件
    - 创建必要的目录结构（logs、config）
    - 交互式引导用户设置核心配置
    """
    
    name = "init"
    help = "初始化项目配置"
    
    # 需要创建的目录
    REQUIRED_DIRS = [
        "logs",
        "config",
        "config/providers",
    ]
    
    # 核心配置项及其描述
    CORE_CONFIG = {
        "API_PORT": {
            "description": "API 监听端口",
            "default": "8081",
            "type": "int",
        },
        "API_HOST": {
            "description": "API 绑定地址",
            "default": "0.0.0.0",
            "type": "str",
        },
        "EXEC_USER": {
            "description": "默认执行用户",
            "default": "ubuntu",
            "type": "str",
        },
        "LOG_LEVEL": {
            "description": "日志级别",
            "default": "INFO",
            "type": "choice",
            "choices": ["DEBUG", "INFO", "WARNING", "ERROR"],
        },
        "ENVIRONMENT": {
            "description": "运行环境",
            "default": "development",
            "type": "choice",
            "choices": ["development", "staging", "production"],
        },
    }
    
    def __init__(self):
        self.printer = Printer()
        self.base_dir = Path.cwd()
        self.env_manager = EnvManager(base_dir=self.base_dir)
    
    def run(self, args: argparse.Namespace) -> int:
        """执行 init 命令"""
        self.printer.header("Agent Nexus 初始化向导")
        
        # 1. 检查并创建目录结构
        self.printer.section("创建目录结构")
        self._create_directories()
        
        # 2. 创建 .env 文件
        self.printer.section("配置环境变量")
        env_created = self._create_env_file(force=args.force)
        
        if not env_created and not args.force:
            self.printer.warning(".env 文件已存在，使用 --force 强制覆盖")
        
        # 3. 交互式配置（如果启用）
        if not args.no_interactive and env_created:
            self.printer.section("基础配置")
            self._interactive_setup()
        
        # 4. 显示完成信息
        self._show_summary()
        
        return 0
    
    def _create_directories(self) -> None:
        """创建必要的目录结构"""
        for dir_name in self.REQUIRED_DIRS:
            dir_path = self.base_dir / dir_name
            if dir_path.exists():
                self.printer.list_item(f"{dir_name}/ (已存在)")
            else:
                dir_path.mkdir(parents=True, exist_ok=True)
                self.printer.success(f"创建目录: {dir_name}/", prefix=False)
    
    def _create_env_file(self, force: bool = False) -> bool:
        """从 .env.example 创建 .env 文件
        
        Args:
            force: 是否强制覆盖
            
        Returns:
            True 如果创建成功
        """
        if self.env_manager.exists() and not force:
            self.printer.info(".env 文件已存在")
            return False
        
        if not self.env_manager.example_exists():
            self.printer.warning(".env.example 文件不存在，创建空的 .env 文件")
            self.env_manager.env_file.touch()
            return True
        
        if self.env_manager.create_from_example(force=force):
            self.printer.success("已创建 .env 文件（从 .env.example 复制）")
            return True
        else:
            self.printer.error("创建 .env 文件失败")
            return False
    
    def _interactive_setup(self) -> None:
        """交互式配置向导"""
        self.printer.print("请设置以下核心配置（按 Enter 使用默认值）：")
        self.printer.print()
        
        for key, config in self.CORE_CONFIG.items():
            value = self._prompt_config(key, config)
            if value:
                self.env_manager.set_value(key, value)
    
    def _prompt_config(self, key: str, config: Dict[str, Any]) -> str:
        """提示用户输入配置值
        
        Args:
            key: 配置项名称
            config: 配置项信息
            
        Returns:
            用户输入的值
        """
        description = config["description"]
        default = config["default"]
        config_type = config.get("type", "str")
        
        if config_type == "choice":
            choices = config.get("choices", [])
            self.printer.print(f"\n{description}:")
            idx, value = self.printer.select(
                f"选择 {key}",
                choices,
                default=choices.index(default) if default in choices else 0,
            )
            return value
        else:
            return self.printer.prompt(f"{description} ({key})", default)
    
    def _show_summary(self) -> None:
        """显示初始化完成摘要"""
        self.printer.print()
        self.printer.success("初始化完成！")
        self.printer.print()
        self.printer.print("下一步操作：")
        self.printer.list_item("编辑 .env 文件配置更多选项")
        self.printer.list_item("运行 'anexus start' 启动服务")
        self.printer.list_item("运行 'anexus config wizard' 进行更详细的配置")
        self.printer.print()
