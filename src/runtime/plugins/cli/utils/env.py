# -*- coding: utf-8 -*-
"""
环境变量管理器

负责 .env 文件的读取、写入和管理。
"""

import os
import re
from pathlib import Path
from typing import Dict, Optional, List, Tuple


class EnvManager:
    """环境变量管理器
    
    管理 .env 文件的读写操作。
    """
    
    def __init__(
        self,
        env_file: Optional[Path] = None,
        env_example: Optional[Path] = None,
        base_dir: Optional[Path] = None,
    ):
        """初始化环境变量管理器
        
        Args:
            env_file: .env 文件路径
            env_example: .env.example 文件路径
            base_dir: 项目根目录
        """
        self.base_dir = base_dir or Path.cwd()
        self.env_file = env_file or (self.base_dir / ".env")
        self.env_example = env_example or (self.base_dir / ".env.example")
    
    def exists(self) -> bool:
        """检查 .env 文件是否存在"""
        return self.env_file.exists()
    
    def example_exists(self) -> bool:
        """检查 .env.example 文件是否存在"""
        return self.env_example.exists()
    
    def load_env(self) -> Dict[str, str]:
        """加载 .env 文件中的环境变量
        
        Returns:
            环境变量字典
        """
        if not self.exists():
            return {}
        
        return self._parse_env_file(self.env_file)
    
    def load_example(self) -> Dict[str, str]:
        """加载 .env.example 文件中的环境变量
        
        Returns:
            环境变量字典
        """
        if not self.example_exists():
            return {}
        
        return self._parse_env_file(self.env_example)
    
    def _parse_env_file(self, file_path: Path) -> Dict[str, str]:
        """解析 .env 文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            环境变量字典
        """
        env_vars = {}
        
        try:
            content = file_path.read_text(encoding="utf-8")
            for line in content.splitlines():
                line = line.strip()
                
                # 跳过空行和注释
                if not line or line.startswith("#"):
                    continue
                
                # 解析 KEY=VALUE 格式
                match = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)=(.*)$', line)
                if match:
                    key, value = match.groups()
                    # 移除引号
                    value = value.strip()
                    if (value.startswith('"') and value.endswith('"')) or \
                       (value.startswith("'") and value.endswith("'")):
                        value = value[1:-1]
                    env_vars[key] = value
                    
        except Exception:
            pass
        
        return env_vars
    
    def create_from_example(self, force: bool = False) -> bool:
        """从 .env.example 创建 .env 文件
        
        Args:
            force: 是否强制覆盖已存在的文件
            
        Returns:
            True 如果创建成功
        """
        if self.exists() and not force:
            return False
        
        if not self.example_exists():
            return False
        
        try:
            content = self.env_example.read_text(encoding="utf-8")
            self.env_file.write_text(content, encoding="utf-8")
            return True
        except Exception:
            return False
    
    def get_value(self, key: str) -> Optional[str]:
        """获取单个环境变量值
        
        先从系统环境变量获取，再从 .env 文件获取。
        
        Args:
            key: 环境变量名
            
        Returns:
            环境变量值，不存在返回 None
        """
        # 先检查系统环境变量
        value = os.environ.get(key)
        if value is not None:
            return value
        
        # 再检查 .env 文件
        env_vars = self.load_env()
        return env_vars.get(key)
    
    def set_value(self, key: str, value: str) -> bool:
        """设置环境变量值到 .env 文件
        
        Args:
            key: 环境变量名
            value: 环境变量值
            
        Returns:
            True 如果设置成功
        """
        try:
            lines = []
            key_found = False
            
            if self.exists():
                content = self.env_file.read_text(encoding="utf-8")
                for line in content.splitlines():
                    stripped = line.strip()
                    
                    # 检查是否是目标 key
                    if stripped and not stripped.startswith("#"):
                        match = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)=', stripped)
                        if match and match.group(1) == key:
                            # 替换值
                            lines.append(f"{key}={value}")
                            key_found = True
                            continue
                    
                    lines.append(line)
            
            # 如果 key 不存在，添加到文件末尾
            if not key_found:
                lines.append(f"\n{key}={value}")
            
            self.env_file.write_text("\n".join(lines), encoding="utf-8")
            return True
            
        except Exception:
            return False
    
    def get_all_keys(self) -> List[str]:
        """获取 .env 文件中的所有 key
        
        Returns:
            key 列表
        """
        env_vars = self.load_env()
        return list(env_vars.keys())
    
    def get_config_sections(self) -> Dict[str, List[Tuple[str, str, str]]]:
        """获取配置分组
        
        从 .env.example 文件中解析配置分组和注释。
        
        Returns:
            配置分组字典，格式为 {section: [(key, value, comment), ...]}
        """
        if not self.example_exists():
            return {}
        
        sections: Dict[str, List[Tuple[str, str, str]]] = {}
        current_section = "General"
        current_comment = ""
        
        try:
            content = self.env_example.read_text(encoding="utf-8")
            for line in content.splitlines():
                line = line.strip()
                
                # 检测 section 标题
                if line.startswith("# ---") and line.endswith("---"):
                    # 提取 section 名称
                    match = re.search(r'# -+ (.+?) (?:\||\-)', line)
                    if match:
                        current_section = match.group(1).strip()
                        if current_section not in sections:
                            sections[current_section] = []
                    continue
                
                # 收集注释
                if line.startswith("#"):
                    comment = line[1:].strip()
                    if comment and not comment.startswith("="):
                        current_comment = comment
                    continue
                
                # 解析环境变量
                if line:
                    match = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)=(.*)$', line)
                    if match:
                        key, value = match.groups()
                        if current_section not in sections:
                            sections[current_section] = []
                        sections[current_section].append((key, value, current_comment))
                        current_comment = ""
                        
        except Exception:
            pass
        
        return sections
    
    def apply_to_environment(self) -> None:
        """将 .env 文件中的变量应用到当前进程环境"""
        env_vars = self.load_env()
        for key, value in env_vars.items():
            if key not in os.environ:
                os.environ[key] = value
