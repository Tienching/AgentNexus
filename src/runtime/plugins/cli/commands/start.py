# -*- coding: utf-8 -*-
"""
start 命令实现

启动 Virtual Human SDK 服务。
"""

import argparse
import os
from pathlib import Path

from . import BaseCommand
from ..utils import ProcessManager, EnvManager, Printer


class StartCommand(BaseCommand):
    """start 命令
    
    启动服务，支持：
    - 前台模式（开发调试，支持热重载）
    - 后台模式（生产运行）
    - 指定端口、Worker数等参数
    """
    
    name = "start"
    help = "启动服务"
    
    # 默认配置
    DEFAULT_HOST = "0.0.0.0"
    DEFAULT_PORT = 8081
    DEFAULT_WORKERS = 1
    
    def __init__(self):
        self.printer = Printer()
        self.base_dir = Path.cwd()
        self.process_manager = ProcessManager(base_dir=self.base_dir)
        self.env_manager = EnvManager(base_dir=self.base_dir)
    
    def run(self, args: argparse.Namespace) -> int:
        """执行 start 命令"""
        # 加载环境变量
        self.env_manager.apply_to_environment()
        
        # 获取配置
        host = args.host or self.env_manager.get_value("API_HOST") or self.DEFAULT_HOST
        port = args.port or int(self.env_manager.get_value("API_PORT") or self.DEFAULT_PORT)
        workers = args.workers or int(self.env_manager.get_value("API_WORKERS") or self.DEFAULT_WORKERS)
        reload = args.reload
        daemon = args.daemon
        
        # 设置环境
        if args.env:
            os.environ["ENVIRONMENT"] = args.env
        
        # 检查是否已在运行
        if self.process_manager.is_running():
            pid = self.process_manager.get_pid()
            self.printer.warning(f"服务已在运行中 (PID: {pid})")
            self.printer.print("使用 'vhsdk stop' 先停止服务，或 'vhsdk status' 查看状态")
            return 1
        
        # 检查 .env 文件
        if not self.env_manager.exists():
            self.printer.warning(".env 文件不存在，使用默认配置")
            self.printer.print("建议先运行 'vhsdk init' 初始化配置")
        
        # 启动服务
        if daemon:
            return self._start_daemon(host, port, workers)
        else:
            return self._start_foreground(host, port, reload)
    
    def _start_foreground(self, host: str, port: int, reload: bool) -> int:
        """前台启动服务
        
        Args:
            host: 绑定地址
            port: 监听端口
            reload: 是否启用热重载
            
        Returns:
            退出码
        """
        self.printer.header("启动 Virtual Human SDK 服务")
        
        mode = "开发模式" if reload else "生产模式"
        self.printer.info(f"运行模式: {mode}")
        self.printer.info(f"监听地址: http://{host}:{port}")
        
        if reload:
            self.printer.info("热重载: 已启用")
        
        self.printer.print()
        self.printer.print("按 Ctrl+C 停止服务...")
        self.printer.print()
        
        # 前台运行（exec 替换当前进程）
        return self.process_manager.start_foreground(host, port, reload)
    
    def _start_daemon(self, host: str, port: int, workers: int) -> int:
        """后台启动服务
        
        Args:
            host: 绑定地址
            port: 监听端口
            workers: Worker 进程数
            
        Returns:
            退出码
        """
        self.printer.info("正在后台启动服务...")
        
        pid = self.process_manager.start_background(host, port, workers)
        
        if pid > 0:
            self.printer.success(f"服务已启动 (PID: {pid})")
            self.printer.print()
            self.printer.key_value("监听地址", f"http://{host}:{port}")
            self.printer.key_value("Worker 进程数", workers)
            self.printer.key_value("PID 文件", self.process_manager.pid_file)
            self.printer.key_value("日志文件", self.process_manager.log_file)
            self.printer.print()
            self.printer.print("使用 'vhsdk status' 查看服务状态")
            self.printer.print("使用 'vhsdk stop' 停止服务")
            return 0
        else:
            self.printer.error("服务启动失败")
            self.printer.print(f"请检查日志文件: {self.process_manager.log_file}")
            return 1
