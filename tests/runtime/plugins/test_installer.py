# -*- coding: utf-8 -*-
"""Unit tests for PluginInstaller package installation logic."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.runtime.plugins import installer as installer_module
from src.runtime.plugins.installer import PluginInstaller


class TestDetectPackageManager:
    """Tests for _detect_package_manager method."""

    def test_detects_uv_when_uv_lock_exists_and_uv_available(self, tmp_path):
        """Returns 'uv' when uv.lock exists and uv command is available."""
        installer = PluginInstaller(config_dir=tmp_path / "config")

        # Create uv.lock in current working directory
        uv_lock = tmp_path / "uv.lock"
        uv_lock.touch()

        with (
            patch("src.runtime.plugins.installer.Path.cwd", return_value=tmp_path),
            patch("src.runtime.plugins.installer.shutil.which", return_value="/usr/bin/uv"),
        ):
            result = installer._detect_package_manager()

        assert result == "uv"

    def test_detects_pip_when_uv_lock_missing(self, tmp_path):
        """Returns 'pip' when uv.lock does not exist."""
        installer = PluginInstaller(config_dir=tmp_path / "config")

        with (
            patch("src.runtime.plugins.installer.Path.cwd", return_value=tmp_path),
            patch("src.runtime.plugins.installer.shutil.which", return_value="/usr/bin/uv"),
        ):
            result = installer._detect_package_manager()

        assert result == "pip"

    def test_detects_pip_when_uv_lock_exists_but_uv_not_available(self, tmp_path):
        """Returns 'pip' when uv.lock exists but uv command is not available."""
        installer = PluginInstaller(config_dir=tmp_path / "config")

        uv_lock = tmp_path / "uv.lock"
        uv_lock.touch()

        with (
            patch("src.runtime.plugins.installer.Path.cwd", return_value=tmp_path),
            patch("src.runtime.plugins.installer.shutil.which", return_value=None),
        ):
            result = installer._detect_package_manager()

        assert result == "pip"


class TestBuildInstallCommand:
    """Tests for _build_install_command method."""

    def test_builds_uv_command_for_single_package(self):
        """Builds uv pip install command for a single package."""
        installer = PluginInstaller()
        result = installer._build_install_command("my-package", "uv")
        assert result == ["uv", "pip", "install", "my-package"]

    def test_builds_uv_command_for_multiple_packages(self):
        """Builds uv pip install command for multiple packages."""
        installer = PluginInstaller()
        result = installer._build_install_command(["pkg1", "pkg2"], "uv")
        assert result == ["uv", "pip", "install", "pkg1", "pkg2"]

    def test_builds_pip_command_for_single_package(self):
        """Builds pip install command using sys.executable for a single package."""
        installer = PluginInstaller()
        result = installer._build_install_command("my-package", "pip")
        assert result == [sys.executable, "-m", "pip", "install", "my-package"]

    def test_builds_pip_command_for_multiple_packages(self):
        """Builds pip install command using sys.executable for multiple packages."""
        installer = PluginInstaller()
        result = installer._build_install_command(["pkg1", "pkg2"], "pip")
        assert result == [sys.executable, "-m", "pip", "install", "pkg1", "pkg2"]


class TestInstallProviderPackage:
    """Tests for _install_provider_package method."""

    def test_success_path_with_pip(self, tmp_path):
        """Returns success result when pip install succeeds."""
        installer = PluginInstaller(config_dir=tmp_path / "config")

        with (
            patch.object(installer, "_detect_package_manager", return_value="pip"),
            patch("src.runtime.plugins.installer.subprocess.run") as mock_run,
        ):
            mock_run.return_value = subprocess.CompletedProcess(
                [sys.executable, "-m", "pip", "install", "test-package"],
                0,
                stdout="Successfully installed test-package",
                stderr="",
            )

            result = installer._install_provider_package("test-provider", "test-package")

        assert result.success is True
        assert result.provider == "test-provider"
        assert result.package_manager == "pip"
        assert "成功" in result.message
        mock_run.assert_called_once()

    def test_success_path_with_uv(self, tmp_path):
        """Returns success result when uv pip install succeeds."""
        installer = PluginInstaller(config_dir=tmp_path / "config")

        with (
            patch.object(installer, "_detect_package_manager", return_value="uv"),
            patch("src.runtime.plugins.installer.subprocess.run") as mock_run,
        ):
            mock_run.return_value = subprocess.CompletedProcess(
                ["uv", "pip", "install", "test-package"],
                0,
                stdout="Installed test-package",
                stderr="",
            )

            result = installer._install_provider_package("test-provider", "test-package")

        assert result.success is True
        assert result.provider == "test-provider"
        assert result.package_manager == "uv"
        assert "成功" in result.message

    def test_failure_path_with_nonzero_exit(self, tmp_path):
        """Returns failure result when subprocess returns non-zero exit code."""
        installer = PluginInstaller(config_dir=tmp_path / "config")

        with (
            patch.object(installer, "_detect_package_manager", return_value="pip"),
            patch("src.runtime.plugins.installer.subprocess.run") as mock_run,
        ):
            mock_run.return_value = subprocess.CompletedProcess(
                [sys.executable, "-m", "pip", "install", "test-package"],
                1,
                stdout="",
                stderr="ERROR: Could not find a version",
            )

            result = installer._install_provider_package("test-provider", "test-package")

        assert result.success is False
        assert result.provider == "test-provider"
        assert result.package_manager == "pip"
        assert "失败" in result.message
        assert "Could not find a version" in result.message

    def test_failure_path_with_stderr_fallback_to_stdout(self, tmp_path):
        """Uses stdout when stderr is empty in error message."""
        installer = PluginInstaller(config_dir=tmp_path / "config")

        with (
            patch.object(installer, "_detect_package_manager", return_value="pip"),
            patch("src.runtime.plugins.installer.subprocess.run") as mock_run,
        ):
            mock_run.return_value = subprocess.CompletedProcess(
                [sys.executable, "-m", "pip", "install", "test-package"],
                1,
                stdout="Installation failed due to error",
                stderr="",
            )

            result = installer._install_provider_package("test-provider", "test-package")

        assert result.success is False
        assert "Installation failed" in result.message

    def test_failure_path_file_not_found(self, tmp_path):
        """Returns failure result when subprocess raises FileNotFoundError."""
        installer = PluginInstaller(config_dir=tmp_path / "config")

        with (
            patch.object(installer, "_detect_package_manager", return_value="uv"),
            patch("src.runtime.plugins.installer.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = FileNotFoundError("uv not found")

            result = installer._install_provider_package("test-provider", "test-package")

        assert result.success is False
        assert result.provider == "test-provider"
        assert result.package_manager == "uv"
        assert "失败" in result.message
        assert "uv not found" in result.message

    def test_failure_path_os_error(self, tmp_path):
        """Returns failure result when subprocess raises OSError."""
        installer = PluginInstaller(config_dir=tmp_path / "config")

        with (
            patch.object(installer, "_detect_package_manager", return_value="pip"),
            patch("src.runtime.plugins.installer.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = OSError("Permission denied")

            result = installer._install_provider_package("test-provider", "test-package")

        assert result.success is False
        assert result.provider == "test-provider"
        assert result.package_manager == "pip"
        assert "失败" in result.message
        assert "Permission denied" in result.message

    def test_multiple_packages_install(self, tmp_path):
        """Installs multiple packages in a single command."""
        installer = PluginInstaller(config_dir=tmp_path / "config")

        with (
            patch.object(installer, "_detect_package_manager", return_value="pip"),
            patch("src.runtime.plugins.installer.subprocess.run") as mock_run,
        ):
            mock_run.return_value = subprocess.CompletedProcess(
                [sys.executable, "-m", "pip", "install", "pkg1", "pkg2"],
                0,
                stdout="Installed",
                stderr="",
            )

            result = installer._install_provider_package("test-provider", ["pkg1", "pkg2"])

        assert result.success is True
        call_args = mock_run.call_args[0][0]
        assert call_args == [sys.executable, "-m", "pip", "install", "pkg1", "pkg2"]


class TestInstallProviderFullFlow:
    """Tests for full install_provider flow."""

    def test_unknown_provider_returns_failure(self, tmp_path):
        """Returns failure when provider is not in AVAILABLE_PROVIDERS."""
        installer = PluginInstaller(config_dir=tmp_path / "config")

        result = installer.install_provider("nonexistent-provider")

        assert result.success is False
        assert result.provider == "nonexistent-provider"
        assert "不存在" in result.message
        assert result.config_path is None
        assert result.package_manager is None

    def test_builtin_provider_skips_package_install(self, tmp_path):
        """Skips package installation for built-in providers (package=None)."""
        installer = PluginInstaller(config_dir=tmp_path / "config")

        with patch("src.runtime.plugins.installer.subprocess.run") as mock_run:
            result = installer.install_provider("claude")

        assert result.success is True
        assert result.package_manager is None
        mock_run.assert_not_called()
        assert result.config_path.exists()

    def test_packaged_provider_full_success_flow(self, tmp_path):
        """Full flow: detect package manager, install package, write config."""
        installer = PluginInstaller(config_dir=tmp_path / "config")
        provider_name = "test-provider"
        provider_info = {
            "name": "Test Provider",
            "package": "test-pkg",
            "config_template": "enabled: true\ncommand: \"test\"\n",
        }

        with (
            patch.dict(installer_module.AVAILABLE_PROVIDERS, {provider_name: provider_info}, clear=False),
            patch.object(installer, "_detect_package_manager", return_value="uv"),
            patch("src.runtime.plugins.installer.subprocess.run") as mock_run,
        ):
            mock_run.return_value = subprocess.CompletedProcess(
                ["uv", "pip", "install", "test-pkg"],
                0,
                stdout="Installed",
                stderr="",
            )

            result = installer.install_provider(provider_name)

        assert result.success is True
        assert result.provider == provider_name
        assert result.package_manager == "uv"
        assert result.config_path.exists()
        assert provider_name in installer._installed_providers

    def test_packaged_provider_install_failure_stops_flow(self, tmp_path):
        """Stops and returns failure when package install fails."""
        installer = PluginInstaller(config_dir=tmp_path / "config")
        provider_name = "fail-provider"
        provider_info = {
            "name": "Fail Provider",
            "package": "fail-pkg",
            "config_template": "enabled: true\ncommand: \"fail\"\n",
        }

        with (
            patch.dict(installer_module.AVAILABLE_PROVIDERS, {provider_name: provider_info}, clear=False),
            patch.object(installer, "_detect_package_manager", return_value="pip"),
            patch("src.runtime.plugins.installer.subprocess.run") as mock_run,
        ):
            mock_run.return_value = subprocess.CompletedProcess(
                [sys.executable, "-m", "pip", "install", "fail-pkg"],
                1,
                stdout="",
                stderr="Package not found",
            )

            result = installer.install_provider(provider_name)

        assert result.success is False
        assert result.config_path is None
        config_path = installer.get_config_path("provider", provider_name)
        assert not config_path.exists()
        assert provider_name not in installer._installed_providers

    def test_config_write_failure_returns_error(self, tmp_path):
        """Returns failure when config write fails."""
        installer = PluginInstaller(config_dir=tmp_path / "config")
        provider_name = "write-fail-provider"
        provider_info = {
            "name": "Write Fail Provider",
            "package": None,
            "config_template": "enabled: true\ncommand: \"test\"\n",
        }

        with (
            patch.dict(installer_module.AVAILABLE_PROVIDERS, {provider_name: provider_info}, clear=False),
            patch.object(installer, "init_config"),
            patch.object(installer, "_write_provider_config", side_effect=OSError("Disk full")),
        ):
            result = installer.install_provider(provider_name)

        assert result.success is False
        assert "配置写入失败" in result.message
        assert "Disk full" in result.message
