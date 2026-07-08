# -*- coding: utf-8 -*-
"""
CLI 参数解析器

定义所有命令和参数结构。
"""

import argparse
from typing import Optional


def create_parser() -> argparse.ArgumentParser:
    """创建主参数解析器
    
    Returns:
        配置好的 ArgumentParser 实例
    """
    parser = argparse.ArgumentParser(
        prog="anexus",
        description="Agent Nexus CLI - 一站式服务管理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  anexus onboard                 # 一站式配置向导（推荐首次使用）
  anexus login wechat            # 微信个人号扫码登录
  anexus init                    # 初始化项目配置
  anexus start                   # 前台启动服务
  anexus start --daemon          # 后台启动服务
  anexus stop                    # 停止服务
  anexus status                  # 查看服务状态
  anexus config wizard           # 交互式配置向导
  anexus install channel telegram  # 安装 Telegram 依赖

更多信息请访问: https://github.com/your-org/agent-nexus
        """,
    )
    
    parser.add_argument(
        "--version", "-V",
        action="version",
        version="%(prog)s 0.1.0",
    )
    
    # 创建子命令解析器
    subparsers = parser.add_subparsers(
        dest="command",
        title="命令",
        description="可用命令列表",
        metavar="COMMAND",
    )
    
    # 注册各子命令
    _add_onboard_parser(subparsers)
    _add_login_parser(subparsers)
    _add_init_parser(subparsers)
    _add_start_parser(subparsers)
    _add_stop_parser(subparsers)
    _add_status_parser(subparsers)
    _add_config_parser(subparsers)
    _add_install_parser(subparsers)
    _add_list_parser(subparsers)

    return parser


def _add_onboard_parser(subparsers) -> None:
    """添加 onboard 命令解析器"""
    parser = subparsers.add_parser(
        "onboard",
        help="一站式配置向导 — 引导完成 Channel 选择、Token 配置、依赖安装和服务启动",
        description="交互式引导向导，帮助你一次性完成 Agent Nexus 的完整配置和启动。",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="重置 .env 文件为默认值后重新配置",
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="跳过 Channel 依赖安装",
    )
    parser.add_argument(
        "--skip-start",
        action="store_true",
        help="跳过服务启动",
    )
    parser.add_argument(
        "--no-interactive",
        action="store_true",
        help="非交互模式（目前不支持）",
    )


def _add_login_parser(subparsers) -> None:
    """添加 login 命令解析器"""
    parser = subparsers.add_parser(
        "login",
        help="登录消息渠道 — 通过扫码等方式获取 Bot Token",
        description="通过扫码等方式获取 Bot Token 并自动保存到 .env 文件。",
    )

    login_subparsers = parser.add_subparsers(
        dest="platform",
        title="平台",
        description="支持的登录平台",
        metavar="PLATFORM",
    )

    # login wechat
    wechat_parser = login_subparsers.add_parser(
        "wechat",
        help="微信个人号扫码登录",
        description="通过扫描二维码登录微信个人号，自动获取并保存 Bot Token。",
    )
    wechat_parser.add_argument(
        "--base-url",
        type=str,
        default=None,
        help="自定义 iLink API Base URL (默认: https://ilinkai.weixin.qq.com)",
    )


def _add_init_parser(subparsers) -> None:
    """添加 init 命令解析器"""
    parser = subparsers.add_parser(
        "init",
        help="初始化项目配置",
        description="初始化项目配置文件和目录结构",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="强制覆盖已存在的配置文件",
    )
    parser.add_argument(
        "--no-interactive",
        action="store_true",
        help="跳过交互式配置，使用默认值",
    )
    parser.add_argument(
        "--template",
        type=str,
        default=None,
        help="使用指定的配置模板",
    )


def _add_start_parser(subparsers) -> None:
    """添加 start 命令解析器"""
    parser = subparsers.add_parser(
        "start",
        help="启动服务",
        description="启动 Agent Nexus 服务",
    )
    parser.add_argument(
        "--daemon", "-d",
        action="store_true",
        help="以后台模式启动服务",
    )
    parser.add_argument(
        "--host", "-H",
        type=str,
        default=None,
        help="绑定的主机地址（默认: 0.0.0.0）",
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=None,
        help="监听端口（默认: 8081）",
    )
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=None,
        help="Worker 进程数（后台模式，默认: 1）",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="启用热重载（仅前台模式）",
    )
    parser.add_argument(
        "--env",
        type=str,
        choices=["development", "staging", "production"],
        default=None,
        help="运行环境",
    )


def _add_stop_parser(subparsers) -> None:
    """添加 stop 命令解析器"""
    parser = subparsers.add_parser(
        "stop",
        help="停止服务",
        description="停止正在运行的服务",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="强制停止服务（SIGKILL）",
    )
    parser.add_argument(
        "--timeout", "-t",
        type=int,
        default=10,
        help="等待服务停止的超时时间（秒，默认: 10）",
    )


def _add_status_parser(subparsers) -> None:
    """添加 status 命令解析器"""
    parser = subparsers.add_parser(
        "status",
        help="查看服务状态",
        description="显示服务运行状态和配置信息",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 格式输出",
    )
    parser.add_argument(
        "--health",
        action="store_true",
        help="执行健康检查",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="显示详细信息",
    )


def _add_config_parser(subparsers) -> None:
    """添加 config 命令解析器"""
    parser = subparsers.add_parser(
        "config",
        help="配置管理",
        description="管理项目配置",
    )
    
    config_subparsers = parser.add_subparsers(
        dest="config_command",
        title="配置命令",
        metavar="SUBCOMMAND",
    )
    
    # config init
    init_parser = config_subparsers.add_parser(
        "init",
        help="初始化配置目录和文件",
    )
    init_parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="强制覆盖已存在的配置",
    )
    
    # config show
    show_parser = config_subparsers.add_parser(
        "show",
        help="显示当前配置",
    )
    show_parser.add_argument(
        "--section",
        type=str,
        default=None,
        help="只显示指定配置节（如 server, redis, channels）",
    )
    show_parser.add_argument(
        "--secrets",
        action="store_true",
        help="显示敏感信息（如 Token）",
    )
    show_parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 格式输出",
    )
    
    # config set
    set_parser = config_subparsers.add_parser(
        "set",
        help="设置配置项",
    )
    set_parser.add_argument(
        "key",
        type=str,
        help="配置项名称（如 API_PORT, REDIS_HOST）",
    )
    set_parser.add_argument(
        "value",
        type=str,
        help="配置项值",
    )
    
    # config wizard
    wizard_parser = config_subparsers.add_parser(
        "wizard",
        help="交互式配置向导",
    )
    wizard_parser.add_argument(
        "--section",
        type=str,
        choices=["server", "redis", "channels", "providers", "all"],
        default="all",
        help="配置特定部分（默认: all）",
    )


def _add_install_parser(subparsers) -> None:
    """添加 install 命令解析器"""
    parser = subparsers.add_parser(
        "install",
        help="安装依赖",
        description="安装 Channel 或 Provider 依赖",
    )
    
    install_subparsers = parser.add_subparsers(
        dest="install_type",
        title="安装类型",
        metavar="TYPE",
    )
    
    # install channel
    channel_parser = install_subparsers.add_parser(
        "channel",
        help="安装消息渠道依赖",
    )
    channel_parser.add_argument(
        "name",
        type=str,
        choices=["telegram", "slack", "discord", "feishu", "whatsapp", "signal", "all"],
        help="Channel 名称或 'all' 安装所有",
    )
    
    # install provider
    provider_parser = install_subparsers.add_parser(
        "provider",
        help="安装 Provider",
    )
    provider_parser.add_argument(
        "name",
        type=str,
        help="Provider 名称（如 claude, codex）",
    )


def _add_list_parser(subparsers) -> None:
    """添加 list 命令解析器（向后兼容）"""
    parser = subparsers.add_parser(
        "list",
        help="列出已安装的插件",
        description="列出已安装的 Providers 和 Channels",
    )
    parser.add_argument(
        "--type",
        type=str,
        choices=["provider", "channel", "all"],
        default="all",
        help="插件类型（默认: all）",
    )
