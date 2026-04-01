Title: Complete provider installer execution path
Files: src/runtime/plugins/installer.py, src/runtime/plugins/cli/commands/install.py, tests/unit/test_plugin_installer.py
Issue: none

Finish the real provider install path so `PluginInstaller.install_provider()` does more than write config. Add small, testable helpers inside `PluginInstaller` to choose `uv` vs `pip`, run the install command when a provider declares a package, and return a clean success/failure result without leaving partial state behind. Keep built-in providers such as `claude` and `gemini` on the config-only path.

Update `InstallCommand._install_provider()` to surface installer failures clearly and keep the CLI output aligned with the actual install result. Add focused unit coverage in `tests/unit/test_plugin_installer.py` for three cases: built-in provider config generation, packaged provider install with mocked subprocess success, and packaged provider install failure.

Why: the assessment found a real TODO in the installer, which means provider installation is not end-to-end today.

Verify with:
`python3 -m pytest tests/unit/test_plugin_installer.py -q`