# -*- coding: utf-8 -*-
"""
config 命令实现

管理项目配置。
"""

import argparse
import json
from pathlib import Path
from typing import Dict, List, Tuple

from . import BaseCommand
from ..utils import EnvManager, Printer


class ConfigCommand(BaseCommand):
    """config 命令
    
    配置管理：
    - config init: 初始化配置目录和文件
    - config show: 显示当前配置
    - config set: 设置单个配置项
    - config wizard: 交互式配置向导
    """
    
    name = "config"
    help = "配置管理"
    
    # 敏感配置项
    SENSITIVE_KEYS = {
        "TELEGRAM_BOT_TOKEN",
        "SLACK_BOT_TOKEN",
        "SLACK_APP_TOKEN",
        "DISCORD_BOT_TOKEN",
        "FEISHU_APP_SECRET",
        "WHATSAPP_BRIDGE_AUTH_TOKEN",
        "WHATSAPP_API_TOKEN",
        "REDIS_PASSWORD",
        "NEXUS_PASSWORD",
    }
    
    # 配置向导分组
    CONFIG_SECTIONS = {
        "server": {
            "title": "服务器配置",
            "keys": [
                ("API_HOST", "API 绑定地址", "0.0.0.0"),
                ("API_PORT", "API 监听端口", "8081"),
                ("API_WORKERS", "Worker 进程数", "1"),
                ("ENVIRONMENT", "运行环境 (development/staging/production)", "development"),
            ],
        },
        "redis": {
            "title": "Redis 配置",
            "keys": [
                ("REDIS_HOST", "Redis 主机地址", "localhost"),
                ("REDIS_PORT", "Redis 端口", "6379"),
                ("REDIS_DB", "Redis 数据库编号", "0"),
                ("REDIS_PASSWORD", "Redis 密码（留空表示无密码）", ""),
            ],
        },
        "channels": {
            "title": "消息渠道配置",
            "keys": [
                ("CHANNELS_ENABLED", "启用消息渠道服务 (true/false)", "true"),
                ("TELEGRAM_BOT_TOKEN", "Telegram Bot Token", ""),
                ("SLACK_BOT_TOKEN", "Slack Bot Token (xoxb-...)", ""),
                ("SLACK_APP_TOKEN", "Slack App Token (xapp-...)", ""),
                ("DISCORD_BOT_TOKEN", "Discord Bot Token", ""),
                ("FEISHU_APP_ID", "飞书 App ID", ""),
                ("FEISHU_APP_SECRET", "飞书 App Secret", ""),
                ("WHATSAPP_API_TOKEN", "WhatsApp Business API Token", ""),
                ("WHATSAPP_PHONE_NUMBER_ID", "WhatsApp Phone Number ID", ""),
                ("WHATSAPP_VERIFY_TOKEN", "WhatsApp Webhook 验证 Token (可选)", ""),
                ("SIGNAL_API_URL", "Signal API URL", "http://localhost:8080"),
                ("SIGNAL_PHONE_NUMBER", "Signal 绑定手机号 (+123456)", ""),
            ],
        },
        "providers": {
            "title": "Provider 配置",
            "keys": [
                ("CLI_COMMAND", "CLI 执行命令（默认 Provider）", "claude"),
                ("CLI_TIMEOUT", "CLI 执行超时（秒）", "600"),
            ],
        },
        "defaults": {
            "title": "默认值配置",
            "keys": [
                ("DEFAULT_PROVIDER", "默认 Provider (claude/codex/codebuddy/hermes)", "codebuddy"),
                ("DEFAULT_ALIAS", "默认 Alias (如 claude-internal 等别名)", ""),
                ("DEFAULT_EXEC_USER", "默认 Exec User 名称", ""),
            ],
        },
        "nexus": {
            "title": "Nexus 控制台配置",
            "keys": [
                ("NEXUS_PASSWORD", "Nexus 登录密码（留空禁用认证）", ""),
                ("NEXUS_SESSION_TTL", "Session 有效期（秒）", "86400"),
            ],
        },
    }
    
    def __init__(self):
        self.printer = Printer()
        self.base_dir = Path.cwd()
        self.env_manager = EnvManager(base_dir=self.base_dir)
        self.config_dir = self.base_dir / "config"
    
    def run(self, args: argparse.Namespace) -> int:
        """执行 config 命令"""
        config_cmd = getattr(args, "config_command", None)
        
        if not config_cmd:
            self.printer.print("请指定配置子命令:")
            self.printer.list_item("anexus config init   - 初始化配置")
            self.printer.list_item("anexus config show   - 显示配置")
            self.printer.list_item("anexus config set KEY VALUE - 设置配置")
            self.printer.list_item("anexus config wizard - 配置向导")
            return 1
        
        if config_cmd == "init":
            return self._cmd_init(args)
        elif config_cmd == "show":
            return self._cmd_show(args)
        elif config_cmd == "set":
            return self._cmd_set(args)
        elif config_cmd == "wizard":
            return self._cmd_wizard(args)
        else:
            self.printer.error(f"未知的配置命令: {config_cmd}")
            return 1
    
    def _cmd_init(self, args: argparse.Namespace) -> int:
        """初始化配置"""
        force = getattr(args, "force", False)
        
        # 创建配置目录
        if self.config_dir.exists() and not force:
            self.printer.warning(f"配置目录已存在: {self.config_dir}")
            self.printer.print("使用 --force 强制覆盖")
            return 1
        
        self.config_dir.mkdir(parents=True, exist_ok=True)
        (self.config_dir / "providers").mkdir(exist_ok=True)
        
        self.printer.success(f"配置目录已初始化: {self.config_dir}")
        
        # 创建 .env 文件
        if not self.env_manager.exists():
            if self.env_manager.create_from_example():
                self.printer.success("已创建 .env 文件")
            else:
                self.printer.warning(".env.example 不存在，跳过 .env 创建")
        
        return 0
    
    def _cmd_show(self, args: argparse.Namespace) -> int:
        """显示配置"""
        section = getattr(args, "section", None)
        show_secrets = getattr(args, "secrets", False)
        output_json = getattr(args, "json", False)
        
        if not self.env_manager.exists():
            self.printer.warning(".env 文件不存在")
            self.printer.print("运行 'anexus init' 或 'anexus config init' 初始化配置")
            return 1
        
        env_vars = self.env_manager.load_env()
        
        # JSON 输出模式
        if output_json:
            config_data = {}
            sections_to_show = [section] if section else list(self.CONFIG_SECTIONS.keys())
            
            for sec_name in sections_to_show:
                if sec_name not in self.CONFIG_SECTIONS:
                    continue
                
                sec_config = self.CONFIG_SECTIONS[sec_name]
                section_data = {}
                
                for key, description, default in sec_config["keys"]:
                    value = env_vars.get(key, default)
                    
                    # 隐藏敏感信息
                    if key in self.SENSITIVE_KEYS and value and not show_secrets:
                        display_value = "***" + value[-4:] if len(value) > 4 else "****"
                    else:
                        display_value = value
                    
                    section_data[key] = {
                        "value": display_value,
                        "description": description,
                        "default": default,
                    }
                
                config_data[sec_name] = section_data
            
            print(json.dumps(config_data, indent=2, ensure_ascii=False))
            return 0
        
        # 表格输出模式
        self.printer.header("当前配置")
        
        sections_to_show = [section] if section else list(self.CONFIG_SECTIONS.keys())
        
        for sec_name in sections_to_show:
            if sec_name not in self.CONFIG_SECTIONS:
                continue
            
            sec_config = self.CONFIG_SECTIONS[sec_name]
            self.printer.section(sec_config["title"])
            
            for key, description, default in sec_config["keys"]:
                value = env_vars.get(key, default)
                
                # 隐藏敏感信息
                if key in self.SENSITIVE_KEYS and value and not show_secrets:
                    display_value = "***" + value[-4:] if len(value) > 4 else "****"
                else:
                    display_value = value or "(未设置)"
                
                self.printer.key_value(key, display_value)
        
        if not show_secrets:
            self.printer.print()
            self.printer.print("(敏感信息已隐藏，使用 --secrets 显示)")
        
        return 0
    
    def _cmd_set(self, args: argparse.Namespace) -> int:
        """设置配置项"""
        key = getattr(args, "key", None)
        value = getattr(args, "value", None)
        
        if not key or value is None:
            self.printer.error("请提供 KEY 和 VALUE")
            self.printer.print("用法: anexus config set KEY VALUE")
            return 1
        
        # 确保 .env 文件存在
        if not self.env_manager.exists():
            if not self.env_manager.create_from_example():
                self.env_manager.env_file.touch()
        
        # 设置值
        if self.env_manager.set_value(key, value):
            self.printer.success(f"已设置 {key}")
            
            # 敏感信息不显示完整值
            if key in self.SENSITIVE_KEYS:
                display_value = "***" + value[-4:] if len(value) > 4 else "****"
            else:
                display_value = value
            self.printer.key_value("新值", display_value)
            return 0
        else:
            self.printer.error(f"设置 {key} 失败")
            return 1
    
    def _cmd_wizard(self, args: argparse.Namespace) -> int:
        """交互式配置向导"""
        section = getattr(args, "section", "all")
        
        self.printer.header("配置向导")
        
        # 确保 .env 文件存在
        if not self.env_manager.exists():
            if self.env_manager.create_from_example():
                self.printer.success("已创建 .env 文件")
            else:
                self.env_manager.env_file.touch()
                self.printer.info("已创建空的 .env 文件")
        
        # 加载当前值
        env_vars = self.env_manager.load_env()
        
        # 确定要配置的分组
        if section == "all":
            sections_to_config = list(self.CONFIG_SECTIONS.keys())
        else:
            sections_to_config = [section]
        
        changes = []
        
        for sec_name in sections_to_config:
            if sec_name not in self.CONFIG_SECTIONS:
                continue
            
            sec_config = self.CONFIG_SECTIONS[sec_name]
            self.printer.section(sec_config["title"])
            
            for key, description, default in sec_config["keys"]:
                current = env_vars.get(key, default)
                
                # 敏感信息的当前值显示
                if key in self.SENSITIVE_KEYS and current:
                    display_current = "***" + current[-4:] if len(current) > 4 else "****"
                else:
                    display_current = current or "(空)"
                
                self.printer.print(f"\n{description}")
                self.printer.print(f"当前值: {display_current}", color="dim")
                
                new_value = self.printer.prompt(f"新值 (按 Enter 保持不变)", "")
                
                if new_value and new_value != current:
                    changes.append((key, new_value))
        
        # 应用更改
        if changes:
            self.printer.section("应用更改")
            
            for key, value in changes:
                if self.env_manager.set_value(key, value):
                    if key in self.SENSITIVE_KEYS:
                        display = "***" + value[-4:] if len(value) > 4 else "****"
                    else:
                        display = value
                    self.printer.success(f"{key} = {display}", prefix=False)
                else:
                    self.printer.error(f"设置 {key} 失败", prefix=False)
            
            self.printer.print()
            self.printer.success(f"已更新 {len(changes)} 个配置项")
        else:
            self.printer.print()
            self.printer.info("没有更改")
        
        return 0
