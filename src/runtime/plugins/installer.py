# -*- coding: utf-8 -*-
"""
插件安装器

管理 Provider 的安装、配置生成。
"""

from pathlib import Path
from typing import List, Optional


# 可用的 Providers
AVAILABLE_PROVIDERS = {
    "claude": {
        "name": "Claude",
        "package": None,  # 内置
        "config_template": """# Claude Provider 配置
enabled: true
command: "claude"
default_model: ""
""",
    },
    "gemini": {
        "name": "Gemini",
        "package": None,  # 内置
        "config_template": """# Gemini Provider 配置
enabled: true
command: "gemini"
default_model: ""
""",
    },
    "codex": {
        "name": "Codex",
        "package": None,  # 未来
        "config_template": """# Codex Provider 配置
enabled: false
command: "codex"
default_model: ""
""",
    },
    "codebuddy": {
        "name": "Codebuddy",
        "package": None,  # 未来
        "config_template": """# Codebuddy Provider 配置
enabled: false
command: "codebuddy"
default_model: ""
""",
    },
}


class PluginInstaller:
    """插件安装器"""

    def __init__(self, config_dir: Optional[Path] = None):
        # 默认配置目录
        if config_dir:
            self.config_dir = config_dir
        else:
            # 优先使用项目目录，否则用户目录
            project_config = Path.cwd() / "config" / "vhsdk"
            user_config = Path.home() / ".config" / "vhsdk"

            if project_config.exists():
                self.config_dir = project_config
            else:
                self.config_dir = user_config

        self._installed_providers: set = {"claude", "gemini"}  # 内置
        self._enabled_providers: set = {"claude", "gemini"}

    def init_config(self) -> None:
        """初始化配置目录"""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        (self.config_dir / "providers").mkdir(exist_ok=True)

        # 生成默认配置
        main_config = self.config_dir / "config.yaml"
        if not main_config.exists():
            main_config.write_text("""# VHSDK 配置
default_provider: claude
log_level: INFO
""")

    def get_config_path(self, plugin_type: str, name: str) -> Path:
        """获取配置文件路径"""
        return self.config_dir / f"{plugin_type}s" / f"{name}.yaml"

    def list_available_providers(self) -> List[str]:
        """列出可用的 Providers"""
        return list(AVAILABLE_PROVIDERS.keys())

    def list_installed_providers(self) -> List[str]:
        """列出已安装的 Providers"""
        # 内置 + 配置文件存在
        result = list(self._installed_providers)
        providers_dir = self.config_dir / "providers"
        if providers_dir.exists():
            for f in providers_dir.glob("*.yaml"):
                if f.stem not in result:
                    result.append(f.stem)
        return result

    def is_enabled(self, plugin_type: str, name: str) -> bool:
        """检查是否启用"""
        if plugin_type != "provider":
            return False

        config_path = self.get_config_path(plugin_type, name)
        if not config_path.exists():
            # 内置默认启用
            if name in ("claude", "gemini"):
                return True
            return False

        # 简单解析 yaml 检查 enabled
        content = config_path.read_text()
        for line in content.split("\n"):
            if line.strip().startswith("enabled:"):
                value = line.split(":", 1)[1].strip().lower()
                return value in ("true", "yes", "1")
        return False

    def install_provider(self, name: str) -> bool:
        """安装 Provider"""
        if name not in AVAILABLE_PROVIDERS:
            return False

        provider_info = AVAILABLE_PROVIDERS[name]

        # 安装依赖（如果有）
        if provider_info.get("package"):
            print(f"  📥 安装依赖: {provider_info['package']}")
            # TODO: 实际调用 pip/uv 安装

        # 生成配置文件
        self.init_config()
        config_path = self.get_config_path("provider", name)
        if not config_path.exists():
            config_path.write_text(provider_info["config_template"])

        self._installed_providers.add(name)
        return True
