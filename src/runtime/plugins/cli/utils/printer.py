# -*- coding: utf-8 -*-
"""
格式化输出工具

提供统一的 CLI 输出格式化功能。
"""

import sys
from typing import Any, Dict, List, Optional, Tuple


class Printer:
    """格式化输出工具
    
    提供 info, success, warning, error, table 等输出方法。
    """
    
    # ANSI 颜色代码
    COLORS = {
        "reset": "\033[0m",
        "bold": "\033[1m",
        "dim": "\033[2m",
        "red": "\033[31m",
        "green": "\033[32m",
        "yellow": "\033[33m",
        "blue": "\033[34m",
        "magenta": "\033[35m",
        "cyan": "\033[36m",
        "white": "\033[37m",
    }
    
    # 图标
    ICONS = {
        "info": "ℹ️ ",
        "success": "✅",
        "warning": "⚠️ ",
        "error": "❌",
        "bullet": "•",
        "arrow": "→",
        "check": "✓",
        "cross": "✗",
        "star": "★",
    }
    
    def __init__(self, color: bool = True, quiet: bool = False):
        """初始化输出工具
        
        Args:
            color: 是否启用颜色输出
            quiet: 是否静默模式（只输出错误）
        """
        self.color = color and self._supports_color()
        self.quiet = quiet
    
    def _supports_color(self) -> bool:
        """检查终端是否支持颜色"""
        # 检查是否是 TTY
        if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
            return False
        
        # 检查 TERM 环境变量
        import os
        term = os.environ.get("TERM", "")
        if term == "dumb":
            return False
        
        # 检查是否强制禁用颜色
        if os.environ.get("NO_COLOR"):
            return False
        
        return True
    
    def _colorize(self, text: str, color: str) -> str:
        """给文本添加颜色
        
        Args:
            text: 文本内容
            color: 颜色名称
            
        Returns:
            带颜色的文本
        """
        if not self.color:
            return text
        
        color_code = self.COLORS.get(color, "")
        reset_code = self.COLORS["reset"]
        return f"{color_code}{text}{reset_code}"
    
    def info(self, message: str, prefix: bool = True) -> None:
        """输出信息消息
        
        Args:
            message: 消息内容
            prefix: 是否添加图标前缀
        """
        if self.quiet:
            return
        
        if prefix:
            icon = self.ICONS["info"]
            message = f"{icon} {message}"
        
        print(self._colorize(message, "cyan"))
    
    def success(self, message: str, prefix: bool = True) -> None:
        """输出成功消息
        
        Args:
            message: 消息内容
            prefix: 是否添加图标前缀
        """
        if self.quiet:
            return
        
        if prefix:
            icon = self.ICONS["success"]
            message = f"{icon} {message}"
        
        print(self._colorize(message, "green"))
    
    def warning(self, message: str, prefix: bool = True) -> None:
        """输出警告消息
        
        Args:
            message: 消息内容
            prefix: 是否添加图标前缀
        """
        if prefix:
            icon = self.ICONS["warning"]
            message = f"{icon} {message}"
        
        print(self._colorize(message, "yellow"))
    
    def error(self, message: str, prefix: bool = True) -> None:
        """输出错误消息
        
        Args:
            message: 消息内容
            prefix: 是否添加图标前缀
        """
        if prefix:
            icon = self.ICONS["error"]
            message = f"{icon} {message}"
        
        print(self._colorize(message, "red"), file=sys.stderr)
    
    def print(self, message: str = "", color: Optional[str] = None) -> None:
        """输出普通消息
        
        Args:
            message: 消息内容
            color: 可选的颜色
        """
        if self.quiet:
            return
        
        if color:
            message = self._colorize(message, color)
        
        print(message)
    
    def header(self, title: str, char: str = "=") -> None:
        """输出标题
        
        Args:
            title: 标题内容
            char: 分隔线字符
        """
        if self.quiet:
            return
        
        width = max(len(title) + 4, 40)
        line = char * width
        
        print()
        print(self._colorize(line, "bold"))
        print(self._colorize(f"  {title}", "bold"))
        print(self._colorize(line, "bold"))
        print()
    
    def section(self, title: str) -> None:
        """输出小节标题
        
        Args:
            title: 标题内容
        """
        if self.quiet:
            return
        
        print()
        print(self._colorize(f"── {title} ──", "bold"))
        print()
    
    def list_item(self, item: str, indent: int = 0) -> None:
        """输出列表项
        
        Args:
            item: 列表项内容
            indent: 缩进级别
        """
        if self.quiet:
            return
        
        spaces = "  " * indent
        bullet = self.ICONS["bullet"]
        print(f"{spaces}{bullet} {item}")
    
    def key_value(self, key: str, value: Any, indent: int = 0) -> None:
        """输出键值对
        
        Args:
            key: 键名
            value: 值
            indent: 缩进级别
        """
        if self.quiet:
            return
        
        spaces = "  " * indent
        key_str = self._colorize(f"{key}:", "bold")
        print(f"{spaces}{key_str} {value}")
    
    def table(
        self,
        headers: List[str],
        rows: List[List[str]],
        align: Optional[List[str]] = None,
    ) -> None:
        """输出表格
        
        Args:
            headers: 表头列表
            rows: 数据行列表
            align: 对齐方式列表（'left', 'center', 'right'）
        """
        if self.quiet:
            return
        
        if not headers and not rows:
            return
        
        # 计算每列最大宽度
        col_count = len(headers) if headers else (len(rows[0]) if rows else 0)
        widths = [0] * col_count
        
        if headers:
            for i, h in enumerate(headers):
                widths[i] = max(widths[i], len(str(h)))
        
        for row in rows:
            for i, cell in enumerate(row):
                if i < col_count:
                    widths[i] = max(widths[i], len(str(cell)))
        
        # 默认对齐方式
        if not align:
            align = ["left"] * col_count
        
        def format_cell(text: str, width: int, alignment: str) -> str:
            if alignment == "center":
                return text.center(width)
            elif alignment == "right":
                return text.rjust(width)
            return text.ljust(width)
        
        # 输出表头
        if headers:
            header_line = " │ ".join(
                format_cell(str(h), widths[i], align[i])
                for i, h in enumerate(headers)
            )
            print(self._colorize(f"  {header_line}", "bold"))
            
            # 分隔线
            sep_line = "─┼─".join("─" * w for w in widths)
            print(self._colorize(f"  {sep_line}", "dim"))
        
        # 输出数据行
        for row in rows:
            row_line = " │ ".join(
                format_cell(str(row[i]) if i < len(row) else "", widths[i], align[i])
                for i in range(col_count)
            )
            print(f"  {row_line}")
    
    def progress(self, current: int, total: int, prefix: str = "", suffix: str = "") -> None:
        """输出进度条
        
        Args:
            current: 当前进度
            total: 总进度
            prefix: 前缀文本
            suffix: 后缀文本
        """
        if self.quiet:
            return
        
        bar_length = 30
        filled = int(bar_length * current / total) if total > 0 else 0
        bar = "█" * filled + "░" * (bar_length - filled)
        percent = (current / total * 100) if total > 0 else 0
        
        line = f"\r{prefix} [{bar}] {percent:.1f}% {suffix}"
        print(line, end="", flush=True)
        
        if current >= total:
            print()  # 完成时换行
    
    def confirm(self, message: str, default: bool = False) -> bool:
        """交互式确认
        
        Args:
            message: 提示消息
            default: 默认值
            
        Returns:
            用户的选择
        """
        suffix = "[Y/n]" if default else "[y/N]"
        prompt = f"{message} {suffix} "
        
        try:
            response = input(self._colorize(prompt, "yellow")).strip().lower()
            if not response:
                return default
            return response in ("y", "yes", "是")
        except (EOFError, KeyboardInterrupt):
            print()
            return default
    
    def prompt(self, message: str, default: Optional[str] = None) -> str:
        """交互式输入
        
        Args:
            message: 提示消息
            default: 默认值
            
        Returns:
            用户输入
        """
        if default:
            prompt = f"{message} [{default}]: "
        else:
            prompt = f"{message}: "
        
        try:
            response = input(self._colorize(prompt, "cyan")).strip()
            return response if response else (default or "")
        except (EOFError, KeyboardInterrupt):
            print()
            return default or ""
    
    def select(
        self,
        message: str,
        options: List[str],
        default: int = 0,
    ) -> Tuple[int, str]:
        """交互式选择
        
        Args:
            message: 提示消息
            options: 选项列表
            default: 默认选项索引
            
        Returns:
            (选项索引, 选项值)
        """
        print(self._colorize(message, "cyan"))
        
        for i, option in enumerate(options):
            marker = self._colorize("→", "green") if i == default else " "
            print(f"  {marker} {i + 1}. {option}")
        
        try:
            response = input(f"请选择 [1-{len(options)}] (默认: {default + 1}): ").strip()
            if not response:
                return default, options[default]
            
            idx = int(response) - 1
            if 0 <= idx < len(options):
                return idx, options[idx]
            
            return default, options[default]
        except (ValueError, EOFError, KeyboardInterrupt):
            print()
            return default, options[default]


# 全局默认实例
_default_printer: Optional[Printer] = None


def get_printer() -> Printer:
    """获取默认的 Printer 实例"""
    global _default_printer
    if _default_printer is None:
        _default_printer = Printer()
    return _default_printer
