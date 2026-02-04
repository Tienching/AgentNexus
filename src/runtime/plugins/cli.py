# -*- coding: utf-8 -*-
"""
vhsdk CLI 入口

用法:
    vhsdk install provider codex
    vhsdk list
    vhsdk config init
"""

import argparse
import sys
from pathlib import Path

from .installer import PluginInstaller


def create_parser() -> argparse.ArgumentParser:
    """创建参数解析器"""
    parser = argparse.ArgumentParser(
        prog="vhsdk",
        description="Virtual Human SDK CLI - 管理 providers",
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # install 命令
    install_parser = subparsers.add_parser("install", help="安装插件")
    install_subparsers = install_parser.add_subparsers(dest="type", help="插件类型")

    # install provider
    provider_parser = install_subparsers.add_parser("provider", help="安装 Provider")
    provider_parser.add_argument("name", help="Provider 名称 (claude/gemini/codex)")

    # list 命令
    list_parser = subparsers.add_parser("list", help="列出已安装的插件")
    list_parser.add_argument("--type", choices=["provider", "all"], default="all")

    # config 命令
    config_parser = subparsers.add_parser("config", help="配置管理")
    config_subparsers = config_parser.add_subparsers(dest="config_cmd", help="配置命令")

    # config init
    init_parser = config_subparsers.add_parser("init", help="初始化配置")
    init_parser.add_argument("--force", action="store_true", help="强制覆盖")

    # config show
    show_parser = config_subparsers.add_parser("show", help="显示配置")

    return parser


def cmd_install_provider(args, installer: PluginInstaller) -> int:
    """安装 Provider"""
    print(f"📦 安装 Provider: {args.name}")

    success = installer.install_provider(args.name)
    if success:
        print(f"✅ Provider '{args.name}' 安装成功！")
        print(f"\n配置文件已生成: {installer.get_config_path('provider', args.name)}")
        return 0
    else:
        print(f"❌ Provider '{args.name}' 不存在或安装失败。")
        print(f"\n可用 Providers: {', '.join(installer.list_available_providers())}")
        return 1


def cmd_list(args, installer: PluginInstaller) -> int:
    """列出插件"""
    print("📋 已安装的插件:\n")

    if args.type in ("provider", "all"):
        print("Providers:")
        providers = installer.list_installed_providers()
        if providers:
            for pv in providers:
                status = "✅ 启用" if installer.is_enabled("provider", pv) else "⏸️  禁用"
                print(f"  - {pv} [{status}]")
        else:
            print("  (无)")

    return 0


def cmd_config_init(args, installer: PluginInstaller) -> int:
    """初始化配置"""
    config_dir = installer.config_dir

    if config_dir.exists() and not args.force:
        print(f"⚠️  配置目录已存在: {config_dir}")
        print("使用 --force 强制覆盖。")
        return 1

    installer.init_config()
    print(f"✅ 配置目录已初始化: {config_dir}")
    return 0


def cmd_config_show(args, installer: PluginInstaller) -> int:
    """显示配置"""
    print(f"📁 配置目录: {installer.config_dir}")
    print()

    if not installer.config_dir.exists():
        print("配置目录不存在，请先运行: vhsdk config init")
        return 1

    # 列出配置文件
    sub_dir = installer.config_dir / "providers"
    if sub_dir.exists():
        print("Providers:")
        for f in sub_dir.glob("*.yaml"):
            print(f"  - {f.name}")
        print()

    return 0


def main(argv=None) -> int:
    """CLI 入口"""
    parser = create_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    installer = PluginInstaller()

    if args.command == "install":
        if args.type == "provider":
            return cmd_install_provider(args, installer)
        else:
            print("请指定安装类型: vhsdk install provider <name>")
            return 1

    elif args.command == "list":
        return cmd_list(args, installer)

    elif args.command == "config":
        if args.config_cmd == "init":
            return cmd_config_init(args, installer)
        elif args.config_cmd == "show":
            return cmd_config_show(args, installer)
        else:
            print("请指定配置命令: vhsdk config init 或 vhsdk config show")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
