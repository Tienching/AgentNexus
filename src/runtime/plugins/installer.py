# -*- coding: utf-8 -*-
"""
插件安装器

管理 Provider 的安装、配置生成。
"""

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Dict, List, Optional, Sequence, TypedDict


# 可用的 Providers


class ProviderInfo(TypedDict):
    """Provider 信息类型。"""

    name: str
    package: Optional[str]
    config_template: str


AVAILABLE_PROVIDERS: Dict[str, ProviderInfo] = {
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
        "package": None,
        "config_template": """# Codex Provider 配置
enabled: false
command: "codex"
default_model: ""
""",
    },
    "codebuddy": {
        "name": "Codebuddy",
        "package": None,
        "config_template": """# Codebuddy Provider 配置
enabled: false
command: "codebuddy"
default_model: ""
""",
    },
}


@dataclass(frozen=True)
class ProviderInstallResult:
    """Provider 安装结果。"""

    provider: str
    success: bool
    message: str
    config_path: Optional[Path] = None
    package_manager: Optional[str] = None

    def __bool__(self) -> bool:
        return self.success


class PluginInstaller:
    """插件安装器"""

    def __init__(self, config_dir: Optional[Path] = None):
        # 默认配置目录
        if config_dir:
            self.config_dir = config_dir
        else:
            # 优先使用项目目录，否则用户目录
            project_config = Path.cwd() / "config" / "anexus"
            user_config = Path.home() / ".config" / "anexus"

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
            main_config.write_text("""# ANEXUS 配置
default_provider: codebuddy
default_alias:
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

    def install_provider(self, name: str) -> ProviderInstallResult:
        """安装 Provider。"""
        if name not in AVAILABLE_PROVIDERS:
            return ProviderInstallResult(
                provider=name,
                success=False,
                message=f"Provider '{name}' 不存在",
            )

        provider_info = AVAILABLE_PROVIDERS[name]
        package = provider_info.get("package")
        package_manager = None

        if package:
            package_result = self._install_provider_package(name, package)
            if not package_result.success:
                return package_result
            package_manager = package_result.package_manager

        try:
            self.init_config()
            config_path = self._write_provider_config(name, provider_info["config_template"])
        except OSError as exc:
            return ProviderInstallResult(
                provider=name,
                success=False,
                message=f"Provider '{name}' 配置写入失败: {exc}",
                package_manager=package_manager,
            )

        self._installed_providers.add(name)
        return ProviderInstallResult(
            provider=name,
            success=True,
            message=f"Provider '{name}' 安装成功",
            config_path=config_path,
            package_manager=package_manager,
        )

    def _detect_package_manager(self) -> str:
        """检测安装 Provider 时使用的包管理器。"""
        if (Path.cwd() / "uv.lock").exists() and shutil.which("uv"):
            return "uv"
        return "pip"

    def _build_install_command(self, package: str | Sequence[str], package_manager: str) -> List[str]:
        """构造安装命令。"""
        packages = [package] if isinstance(package, str) else list(package)

        if package_manager == "uv":
            return ["uv", "pip", "install", *packages]

        return [sys.executable, "-m", "pip", "install", *packages]

    def _install_provider_package(self, name: str, package: str | Sequence[str]) -> ProviderInstallResult:
        """安装 Provider 依赖包。"""
        package_manager = self._detect_package_manager()
        cmd = self._build_install_command(package, package_manager)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            return ProviderInstallResult(
                provider=name,
                success=False,
                message=f"Provider '{name}' 依赖安装失败: {exc}",
                package_manager=package_manager,
            )
        except OSError as exc:
            return ProviderInstallResult(
                provider=name,
                success=False,
                message=f"Provider '{name}' 依赖安装失败: {exc}",
                package_manager=package_manager,
            )

        if result.returncode != 0:
            error_text = (result.stderr or result.stdout or "未知错误").strip()
            return ProviderInstallResult(
                provider=name,
                success=False,
                message=f"Provider '{name}' 依赖安装失败: {error_text}",
                package_manager=package_manager,
            )

        return ProviderInstallResult(
            provider=name,
            success=True,
            message=f"Provider '{name}' 依赖安装成功",
            package_manager=package_manager,
        )

    def _write_provider_config(self, name: str, config_template: str) -> Path:
        """原子写入 Provider 配置。"""
        config_path = self.get_config_path("provider", name)
        if config_path.exists():
            return config_path

        temp_path = config_path.with_suffix(".yaml.tmp")

        try:
            temp_path.write_text(config_template)
            temp_path.replace(config_path)
        except OSError:
            if temp_path.exists():
                temp_path.unlink()
            raise

        return config_path
