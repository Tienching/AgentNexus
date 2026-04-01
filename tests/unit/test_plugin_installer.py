# -*- coding: utf-8 -*-

import subprocess
from unittest.mock import patch

from src.runtime.plugins import installer as installer_module
from src.runtime.plugins.installer import PluginInstaller


class TestPluginInstaller:
    def test_builtin_provider_generates_config_without_package_install(self, tmp_path):
        installer = PluginInstaller(config_dir=tmp_path / "config")

        with patch("src.runtime.plugins.installer.subprocess.run") as mock_run:
            result = installer.install_provider("claude")

        config_path = installer.get_config_path("provider", "claude")

        assert result.success is True
        assert result.provider == "claude"
        assert result.package_manager is None
        assert result.config_path == config_path
        assert config_path.exists()
        assert 'command: "claude"' in config_path.read_text()
        mock_run.assert_not_called()

    def test_packaged_provider_installs_with_uv_before_writing_config(self, tmp_path):
        installer = PluginInstaller(config_dir=tmp_path / "config")
        provider_name = "mock-provider"
        provider_info = {
            "name": "Mock Provider",
            "package": "mock-package",
            "config_template": "enabled: true\ncommand: \"mock\"\n",
        }

        with patch.dict(installer_module.AVAILABLE_PROVIDERS, {provider_name: provider_info}, clear=False):
            with (
                patch.object(installer, "_detect_package_manager", return_value="uv"),
                patch("src.runtime.plugins.installer.subprocess.run") as mock_run,
            ):
                mock_run.return_value = subprocess.CompletedProcess(
                    ["uv", "pip", "install", "mock-package"],
                    0,
                    stdout="installed",
                    stderr="",
                )

                result = installer.install_provider(provider_name)

        config_path = installer.get_config_path("provider", provider_name)

        assert result.success is True
        assert result.provider == provider_name
        assert result.package_manager == "uv"
        assert result.config_path == config_path
        assert config_path.exists()
        assert provider_name in installer.list_installed_providers()
        mock_run.assert_called_once_with(
            ["uv", "pip", "install", "mock-package"],
            capture_output=True,
            text=True,
        )

    def test_packaged_provider_install_failure_does_not_write_config(self, tmp_path):
        installer = PluginInstaller(config_dir=tmp_path / "config")
        provider_name = "broken-provider"
        provider_info = {
            "name": "Broken Provider",
            "package": "broken-package",
            "config_template": "enabled: true\ncommand: \"broken\"\n",
        }

        with patch.dict(installer_module.AVAILABLE_PROVIDERS, {provider_name: provider_info}, clear=False):
            with (
                patch.object(installer, "_detect_package_manager", return_value="pip"),
                patch("src.runtime.plugins.installer.subprocess.run") as mock_run,
            ):
                mock_run.return_value = subprocess.CompletedProcess(
                    ["python", "-m", "pip", "install", "broken-package"],
                    1,
                    stdout="",
                    stderr="install failed",
                )

                result = installer.install_provider(provider_name)

        config_path = installer.get_config_path("provider", provider_name)

        assert result.success is False
        assert result.provider == provider_name
        assert result.package_manager == "pip"
        assert result.config_path is None
        assert "install failed" in result.message
        assert not config_path.exists()
        assert provider_name not in installer._installed_providers
