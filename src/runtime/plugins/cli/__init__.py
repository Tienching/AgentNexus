# -*- coding: utf-8 -*-
"""
anexus CLI - Agent Nexus 命令行工具

提供以下命令：
    anexus onboard   - 一站式配置向导（推荐首次使用）
    anexus init      - 初始化项目配置
    anexus start     - 启动服务
    anexus stop      - 停止服务
    anexus status    - 查看服务状态
    anexus config    - 配置管理
    anexus install   - 安装依赖
    anexus list      - 列出已安装的插件

使用 `anexus --help` 查看所有可用命令。
"""

import sys
from typing import List, Optional

from .parser import create_parser
from .commands import (
    InitCommand,
    StartCommand,
    StopCommand,
    StatusCommand,
    ConfigCommand,
    InstallCommand,
    ListCommand,
    OnboardCommand,
)

__version__ = "0.1.0"

# 命令注册表
COMMANDS = {
    "onboard": OnboardCommand(),
    "init": InitCommand(),
    "start": StartCommand(),
    "stop": StopCommand(),
    "status": StatusCommand(),
    "config": ConfigCommand(),
    "install": InstallCommand(),
    "list": ListCommand(),
}


def main(argv: Optional[List[str]] = None) -> int:
    """CLI 主入口
    
    Args:
        argv: 命令行参数，None 时使用 sys.argv[1:]
        
    Returns:
        退出码：0=成功，1=错误，2=用户中断
    """
    parser = create_parser()
    args = parser.parse_args(argv)
    
    # 没有命令时显示帮助
    if not args.command:
        parser.print_help()
        return 0
    
    # 获取并执行命令
    command = COMMANDS.get(args.command)
    if command is None:
        print(f"❌ 未知命令: {args.command}")
        parser.print_help()
        return 1
    
    try:
        return command.run(args)
    except KeyboardInterrupt:
        print("\n⚠️  操作已取消")
        return 2
    except Exception as e:
        print(f"❌ 执行出错: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
