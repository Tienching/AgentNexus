# -*- coding: utf-8 -*-
"""
stop 命令实现

停止正在运行的服务。
"""

import argparse
from pathlib import Path

from . import BaseCommand
from ..utils import ProcessManager, Printer


class StopCommand(BaseCommand):
    """stop 命令
    
    优雅停止正在运行的服务：
    - 发送 SIGTERM 信号
    - 等待进程退出
    - 支持强制停止（SIGKILL）
    - 清理 PID 文件
    """
    
    name = "stop"
    help = "停止服务"
    
    def __init__(self):
        self.printer = Printer()
        self.base_dir = Path.cwd()
        self.process_manager = ProcessManager(base_dir=self.base_dir)
    
    def run(self, args: argparse.Namespace) -> int:
        """执行 stop 命令"""
        force = args.force
        timeout = args.timeout
        
        # 检查服务是否在运行
        pid = self.process_manager.get_pid()
        
        if pid is None:
            self.printer.info("没有找到正在运行的服务")
            return 0
        
        if not self.process_manager.is_running():
            self.printer.warning(f"PID 文件存在但进程 {pid} 已停止，清理 PID 文件")
            self.process_manager.remove_pid()
            return 0
        
        # 停止服务
        mode = "强制" if force else "优雅"
        self.printer.info(f"正在{mode}停止服务 (PID: {pid})...")
        
        success = self.process_manager.stop_process(force=force, timeout=timeout)
        
        if success:
            self.printer.success("服务已停止")
            return 0
        else:
            self.printer.error("停止服务失败")
            self.printer.print("尝试使用 'vhsdk stop --force' 强制停止")
            return 1
