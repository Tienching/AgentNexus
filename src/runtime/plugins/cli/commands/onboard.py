# -*- coding: utf-8 -*-
"""
onboard 命令实现

一站式引导用户完成 Agent Nexus 的初始化配置和启动。
类似 openclaw onboard，交互式向导引导用户选择 Channel、配置 Token、安装依赖，
最终启动服务。
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import BaseCommand
from ..utils import EnvManager, Printer


# Channel 定义：(显示名称, env 变量列表, pyproject extra 名称, 创建说明 URL)
CHANNEL_REGISTRY: Dict[str, Dict] = {
    "telegram": {
        "display": "Telegram",
        "extra": "telegram",
        "env_keys": [
            ("TELEGRAM_BOT_TOKEN", "Telegram Bot Token", True,
             "从 @BotFather 获取: https://t.me/BotFather"),
        ],
        "optional_keys": [
            ("TELEGRAM_ALLOWED_USERS", "允许的用户 ID (逗号分隔, 留空允许所有)", False, ""),
        ],
        "doc_url": "https://core.telegram.org/bots#how-do-i-create-a-bot",
    },
    "slack": {
        "display": "Slack",
        "extra": "slack",
        "env_keys": [
            ("SLACK_BOT_TOKEN", "Slack Bot OAuth Token (xoxb-...)", True,
             "从 Slack App 管理页获取: https://api.slack.com/apps"),
            ("SLACK_APP_TOKEN", "Slack App Token - Socket Mode (xapp-...)", True,
             "在 App 设置 → Basic Information → App-Level Tokens 创建"),
        ],
        "optional_keys": [],
        "doc_url": "https://api.slack.com/start/quickstart",
    },
    "discord": {
        "display": "Discord",
        "extra": "discord",
        "env_keys": [
            ("DISCORD_BOT_TOKEN", "Discord Bot Token", True,
             "从 Discord Developer Portal 获取: https://discord.com/developers/applications"),
        ],
        "optional_keys": [],
        "doc_url": "https://discord.com/developers/docs/getting-started",
    },
    "feishu": {
        "display": "飞书 (Feishu/Lark)",
        "extra": "feishu",
        "env_keys": [
            ("FEISHU_APP_ID", "飞书应用 App ID", True,
             "从飞书开放平台获取: https://open.feishu.cn/app"),
            ("FEISHU_APP_SECRET", "飞书应用 App Secret", True,
             "在应用凭证页面获取"),
        ],
        "optional_keys": [
            ("FEISHU_VERIFICATION_TOKEN", "Verification Token (事件订阅验证)", False, ""),
            ("FEISHU_ENCRYPT_KEY", "Encrypt Key (事件加密密钥)", False, ""),
        ],
        "doc_url": "https://open.feishu.cn/document/home/introduction-to-custom-app-development/self-built-application-development-process",
    },
    "whatsapp": {
        "display": "WhatsApp",
        "extra": "whatsapp",
        "env_keys": [
            ("WHATSAPP_API_TOKEN", "WhatsApp Business API Token", True,
             "从 Meta Developer Portal 获取"),
            ("WHATSAPP_PHONE_NUMBER_ID", "WhatsApp Phone Number ID", True,
             "在 WhatsApp Business 设置中获取"),
        ],
        "optional_keys": [
            ("WHATSAPP_VERIFY_TOKEN", "Webhook 验证 Token", False, ""),
        ],
        "doc_url": "https://developers.facebook.com/docs/whatsapp/cloud-api/get-started",
    },
    "signal": {
        "display": "Signal",
        "extra": "signal",
        "env_keys": [
            ("SIGNAL_PHONE_NUMBER", "Signal 绑定手机号 (E.164 格式, 如 +1234567890)", True,
             "需要先通过 signal-cli 注册号码"),
        ],
        "optional_keys": [
            ("SIGNAL_API_URL", "Signal CLI REST API 地址", False,
             "默认: http://localhost:8080"),
        ],
        "doc_url": "https://github.com/bbernhard/signal-cli-rest-api",
    },
    "wechat": {
        "display": "微信个人号 (WeChat Personal)",
        "extra": None,  # 无需额外依赖，httpx 和 qrcode 已是核心依赖
        "env_keys": [
            ("WECHAT_BOT_TOKEN", "WeChat Bot Token", True,
             "通过扫码登录获取，运行 'anexus login wechat'"),
        ],
        "optional_keys": [],
        "doc_url": "",
        "login_action": "wechat",  # 标记：使用交互式扫码登录而非手动输入 Token
    },
}

# 必要目录
REQUIRED_DIRS = ["logs", "config", "config/providers"]

# 核心服务配置
CORE_CONFIG = [
    ("API_HOST", "API 绑定地址", "0.0.0.0"),
    ("API_PORT", "API 监听端口", "8081"),
    ("EXEC_USER", "默认执行用户", "ubuntu"),
]

# Provider 选择
PROVIDER_CHOICES = {
    "codebuddy": {
        "display": "CodeBuddy (默认)",
        "command": "codebuddy",
        "install_hint": "请先安装 CodeBuddy CLI，并确保 `codebuddy` 已加入 PATH。",
        "auth_hint": "如果 CLI 需要认证，请先在当前环境完成登录。",
    },
    "claude": {
        "display": "Claude CLI",
        "command": "claude",
        "install_hint": "请先安装 Claude CLI，并确保 `claude` 已加入 PATH。",
        "auth_hint": "安装后运行 `claude login` 完成认证。",
    },
    "gemini": {
        "display": "Gemini CLI",
        "command": "gemini",
        "install_hint": "请先安装 Gemini CLI，并确保 `gemini` 已加入 PATH。",
        "auth_hint": "安装后先完成 Gemini CLI 的登录或 API 配置。",
    },
    "codex": {
        "display": "Codex CLI",
        "command": "codex",
        "install_hint": "请先安装 Codex CLI，并确保 `codex` 已加入 PATH。",
        "auth_hint": "安装后运行 `codex auth` 完成认证。",
    },
}


class OnboardCommand(BaseCommand):
    """onboard 命令

    一站式引导向导：
    1. 环境检查 + 目录创建
    2. 选择并配置 Channel (Telegram / Slack / Discord / 飞书 / WhatsApp / Signal)
    3. 选择默认 Provider
    4. 安装 Channel 依赖
    5. 启动服务
    """

    name = "onboard"
    help = "一站式配置向导 — 引导完成 Channel 选择、Token 配置、依赖安装和服务启动"

    def __init__(self):
        self.printer = Printer()
        self.base_dir = Path.cwd()
        self.env_manager = EnvManager(base_dir=self.base_dir)

    def run(self, args: argparse.Namespace) -> int:
        """执行 onboard 向导"""
        reset = getattr(args, "reset", False)
        skip_install = getattr(args, "skip_install", False)
        skip_start = getattr(args, "skip_start", False)
        non_interactive = getattr(args, "no_interactive", False)

        if non_interactive:
            self.printer.error("onboard 命令需要交互式终端，请去掉 --no-interactive")
            return 1

        # ── 欢迎 ──
        self._print_banner()

        # ── 风险确认 ──
        if not self.printer.confirm("该向导将引导你完成 Agent Nexus 的完整配置，是否继续？", default=True):
            self.printer.info("已取消")
            return 2

        # ── Step 0: 环境检查 ──
        self.printer.section("Step 1/6 · 环境检查")
        self._ensure_directories()
        self._ensure_env_file(reset=reset)

        # ── Step 1: 核心服务配置 ──
        self.printer.section("Step 2/6 · 核心服务配置")
        self._configure_core()

        # ── Step 2: Provider 选择 ──
        self.printer.section("Step 3/6 · 选择默认 Provider")
        self._configure_provider()

        # ── Step 3: Channel 选择与配置 ──
        self.printer.section("Step 4/6 · 选择并配置消息渠道 (Channel)")
        selected_channels = self._configure_channels()

        # ── Step 4: 安装依赖 ──
        if not skip_install and selected_channels:
            self.printer.section("Step 5/6 · 安装 Channel 依赖")
            self._install_channels(selected_channels)
        else:
            self.printer.section("Step 5/6 · 安装 Channel 依赖")
            if skip_install:
                self.printer.info("已跳过依赖安装 (--skip-install)")
            elif not selected_channels:
                self.printer.info("未选择任何 Channel，跳过依赖安装")

        # ── Step 5: 启动服务 ──
        self.printer.section("Step 6/6 · 启动服务")
        if skip_start:
            self.printer.info("已跳过服务启动 (--skip-start)")
            self._show_summary(selected_channels, started=False)
        else:
            started = self._offer_start()
            self._show_summary(selected_channels, started=started)

        return 0

    # ─── Banner ─────────────────────────────────────────────────────────

    def _print_banner(self) -> None:
        self.printer.print()
        self.printer.print(self.printer._colorize(
            "╔══════════════════════════════════════════════════════╗", "cyan"))
        self.printer.print(self.printer._colorize(
            "║                                                      ║", "cyan"))
        self.printer.print(self.printer._colorize(
            "║       🤖  Agent Nexus — Onboard Wizard         ║", "cyan"))
        self.printer.print(self.printer._colorize(
            "║                                                      ║", "cyan"))
        self.printer.print(self.printer._colorize(
            "║   一站式引导你完成 Channel 选择、Token 配置、          ║", "cyan"))
        self.printer.print(self.printer._colorize(
            "║   依赖安装与服务启动。                                ║", "cyan"))
        self.printer.print(self.printer._colorize(
            "║                                                      ║", "cyan"))
        self.printer.print(self.printer._colorize(
            "╚══════════════════════════════════════════════════════╝", "cyan"))
        self.printer.print()

    # ─── Step 0: 环境检查 ───────────────────────────────────────────────

    def _ensure_directories(self) -> None:
        for dir_name in REQUIRED_DIRS:
            dir_path = self.base_dir / dir_name
            if dir_path.exists():
                self.printer.list_item(f"{dir_name}/ ✓")
            else:
                dir_path.mkdir(parents=True, exist_ok=True)
                self.printer.success(f"创建目录: {dir_name}/", prefix=False)

    def _ensure_env_file(self, reset: bool = False) -> None:
        if self.env_manager.exists() and not reset:
            self.printer.list_item(".env 文件已存在 ✓")
            overwrite = self.printer.confirm("是否要基于 .env.example 重置 .env？（现有配置会被覆盖）", default=False)
            if overwrite:
                self.env_manager.create_from_example(force=True)
                self.printer.success("已重置 .env 文件")
        else:
            if self.env_manager.example_exists():
                self.env_manager.create_from_example(force=True)
                self.printer.success("已从 .env.example 创建 .env 文件")
            else:
                self.env_manager.env_file.touch()
                self.printer.warning(".env.example 不存在，已创建空 .env 文件")

    # ─── Step 1: 核心服务配置 ──────────────────────────────────────────

    def _configure_core(self) -> None:
        env_vars = self.env_manager.load_env()

        self.printer.print("配置核心服务参数（按 Enter 使用当前值/默认值）：")
        self.printer.print()

        for key, description, default_val in CORE_CONFIG:
            current = env_vars.get(key, default_val)
            new_val = self.printer.prompt(f"{description} ({key})", current)
            if new_val and new_val != current:
                self.env_manager.set_value(key, new_val)

    # ─── Step 2: Provider 选择 ─────────────────────────────────────────

    def _configure_provider(self) -> None:
        env_vars = self.env_manager.load_env()
        current_provider = env_vars.get("DEFAULT_PROVIDER", "codebuddy")

        provider_names = list(PROVIDER_CHOICES.keys())
        provider_displays = [PROVIDER_CHOICES[p]["display"] for p in provider_names]

        # 标记当前选中
        default_idx = 0
        for i, name in enumerate(provider_names):
            if name == current_provider:
                default_idx = i
                provider_displays[i] += " (当前)"
                break

        idx, _ = self.printer.select("选择默认 AI Provider:", provider_displays, default=default_idx)
        chosen_provider = provider_names[idx]
        chosen_command = PROVIDER_CHOICES[chosen_provider]["command"]

        self.env_manager.set_value("DEFAULT_PROVIDER", chosen_provider)
        self.env_manager.set_value("CLI_COMMAND", chosen_command)
        self.printer.success(f"已设置默认 Provider: {chosen_provider}")

    # ─── Step 3: Channel 选择与配置 ────────────────────────────────────

    def _configure_channels(self) -> List[str]:
        """引导用户选择并配置 Channels，返回选中的 channel 名称列表"""
        env_vars = self.env_manager.load_env()

        # 显示可用 Channel 列表
        channel_names = list(CHANNEL_REGISTRY.keys())
        display_options = []
        for name in channel_names:
            ch = CHANNEL_REGISTRY[name]
            # 检测是否已配置
            configured = self._is_channel_configured(name, env_vars)
            status = " ✅ 已配置" if configured else ""
            display_options.append(f"{ch['display']}{status}")

        self.printer.print("你可以同时启用多个 Channel，逐个进行配置。")
        self.printer.print("每个 Channel 需要对应平台的 Bot Token / API Key。")
        self.printer.print()

        # 多选 Channel
        selected_channels = self._multi_select(
            "选择要启用的 Channel（输入编号，逗号分隔，如 1,2,3）：",
            display_options,
        )

        if not selected_channels:
            self.printer.warning("未选择任何 Channel，稍后可通过 'anexus config wizard --section channels' 配置")
            return []

        selected_names = [channel_names[i] for i in selected_channels]

        self.printer.print()
        self.printer.success(f"已选择: {', '.join(CHANNEL_REGISTRY[n]['display'] for n in selected_names)}")
        self.printer.print()

        # 逐个配置每个 Channel
        for name in selected_names:
            self._configure_single_channel(name)

        # 确保 CHANNELS_ENABLED=true
        self.env_manager.set_value("CHANNELS_ENABLED", "true")

        return selected_names

    def _is_channel_configured(self, name: str, env_vars: Dict[str, str]) -> bool:
        """检查某 Channel 的必填 Token 是否都已配置"""
        ch = CHANNEL_REGISTRY[name]
        for key, _, required, _ in ch["env_keys"]:
            if required and not env_vars.get(key):
                return False
        return True

    def _configure_single_channel(self, name: str) -> None:
        """配置单个 Channel 的所有 Token"""
        ch = CHANNEL_REGISTRY[name]
        env_vars = self.env_manager.load_env()

        self.printer.section(f"配置 {ch['display']}")

        # 显示创建说明
        if ch.get("doc_url"):
            self.printer.print(f"📖 创建指南: {ch['doc_url']}")
            self.printer.print()

        # ── 特殊处理：交互式扫码登录 ──
        login_action = ch.get("login_action")
        if login_action == "wechat":
            # 检查是否已有 Token
            current_token = env_vars.get("WECHAT_BOT_TOKEN", "")
            if current_token:
                self.printer.print(f"当前 Token: {self._mask_token(current_token)}", color="dim")
                if not self.printer.confirm("是否重新扫码登录（覆盖现有 Token）？", default=False):
                    self.printer.success(f"{ch['display']} 保持现有配置 ✓")
                    return

            if self.printer.confirm("是否现在进行微信扫码登录？", default=True):
                success = self._wechat_qr_login()
                if success:
                    self.printer.success(f"{ch['display']} 配置完成 ✓")
                    return
                else:
                    self.printer.warning("扫码登录未成功，你可以稍后运行 'anexus login wechat' 重试")
                    return
            else:
                self.printer.info("跳过扫码登录。稍后可运行 'anexus login wechat' 获取 Token")
                return

        # ── 常规流程：手动输入 Token ──

        # 必填项
        for key, description, required, hint in ch["env_keys"]:
            current = env_vars.get(key, "")
            if current:
                display_current = self._mask_token(current)
                self.printer.print(f"当前值: {display_current}", color="dim")

            if hint:
                self.printer.print(f"   💡 {hint}", color="dim")

            new_val = self.printer.prompt(
                f"{'[必填] ' if required else ''}{description}",
                current,
            )
            if new_val:
                self.env_manager.set_value(key, new_val)
            elif required and not current:
                self.printer.warning(f"⚠️  {key} 是必填项，Channel 可能无法启动")

        # 可选项
        if ch.get("optional_keys"):
            show_optional = self.printer.confirm("是否配置可选参数？", default=False)
            if show_optional:
                for key, description, _, hint in ch["optional_keys"]:
                    current = env_vars.get(key, "")
                    if hint:
                        self.printer.print(f"   💡 {hint}", color="dim")
                    new_val = self.printer.prompt(f"{description}", current)
                    if new_val:
                        self.env_manager.set_value(key, new_val)

        self.printer.success(f"{ch['display']} 配置完成 ✓")

    def _wechat_qr_login(self) -> bool:
        """在 onboard 流程中执行微信扫码登录

        Returns:
            True 如果登录成功，False 如果失败或取消
        """
        try:
            from channels.wechat_login import (
                LoginError,
                LoginTimeoutError,
                QRCodeExpiredError,
                WeChatQRLogin,
            )
        except ImportError:
            self.printer.error("无法导入微信登录模块")
            return False

        login_client = WeChatQRLogin()

        def on_qr(qr_text: str) -> None:
            self.printer.print()
            self.printer.print(qr_text)
            self.printer.print()

        def on_status(status: str, message: str) -> None:
            status_icons = {
                "fetching_qr": "🔄",
                "wait": "⏳",
                "scaned": "📱",
                "confirmed": "✅",
                "expired": "⏰",
                "success": "🎉",
            }
            icon = status_icons.get(status, "ℹ️")
            self.printer.print(f"  {icon} {message}")

        try:
            result = login_client.login(on_qr=on_qr, on_status=on_status)
        except (LoginTimeoutError, QRCodeExpiredError, LoginError) as e:
            self.printer.error(str(e))
            return False
        except KeyboardInterrupt:
            self.printer.warning("登录已取消")
            return False
        except Exception as e:
            self.printer.error(f"未知错误: {e}")
            return False

        # 保存 Token
        self.env_manager.set_value("WECHAT_BOT_TOKEN", result.bot_token)
        self.printer.success("WECHAT_BOT_TOKEN 已保存到 .env")

        if result.base_url and result.base_url != "https://ilinkai.weixin.qq.com":
            self.env_manager.set_value("WECHAT_BASE_URL", result.base_url)
            self.printer.success(f"WECHAT_BASE_URL 已保存: {result.base_url}")

        return True

    # ─── Step 4: 安装依赖 ──────────────────────────────────────────────

    def _install_channels(self, channels: List[str]) -> None:
        """安装选中 Channel 的 Python 依赖"""
        extras = []
        for name in channels:
            ch = CHANNEL_REGISTRY.get(name)
            if ch and ch.get("extra"):
                extras.append(ch["extra"])

        if not extras:
            self.printer.info("所选 Channel 无需额外依赖")
            return

        # 合并安装
        install_str = ",".join(extras)
        self.printer.print(f"将安装以下可选依赖: [{install_str}]")
        self.printer.print()

        if not self.printer.confirm("是否立即安装？", default=True):
            self.printer.info("跳过安装。稍后可运行:")
            for extra in extras:
                self.printer.list_item(f"anexus install channel {extra}")
            return

        pkg_mgr = self._detect_package_manager()

        for extra in extras:
            self.printer.info(f"安装 [{extra}] ...")
            if pkg_mgr == "uv":
                cmd = ["uv", "pip", "install", "-e", f".[{extra}]"]
            else:
                cmd = [sys.executable, "-m", "pip", "install", "-e", f".[{extra}]"]

            try:
                result = subprocess.run(cmd, cwd=self.base_dir, capture_output=True, text=True)
                if result.returncode == 0:
                    self.printer.success(f"[{extra}] 安装成功 ✓")
                else:
                    self.printer.error(f"[{extra}] 安装失败")
                    if result.stderr:
                        # 只显示最后几行错误
                        err_lines = result.stderr.strip().splitlines()[-5:]
                        for line in err_lines:
                            self.printer.print(f"  {line}", color="red")
            except FileNotFoundError:
                self.printer.error(f"命令未找到: {cmd[0]}")

    # ─── Step 5: 启动服务 ──────────────────────────────────────────────

    def _offer_start(self) -> bool:
        """询问是否启动服务"""
        if not self.printer.confirm("是否立即启动 Agent Nexus 服务？", default=True):
            self.printer.info("跳过启动。稍后可运行 'anexus start' 启动服务")
            return False

        _, mode = self.printer.select("选择启动方式:", ["前台运行 (推荐调试用)", "后台运行 (daemon)"], default=0)

        daemon = mode.startswith("后台")

        self.printer.print()
        self.printer.info("正在启动服务...")

        try:
            from ..utils import ProcessManager
            pm = ProcessManager(base_dir=self.base_dir)

            # 加载 .env 到当前进程环境
            self.env_manager.apply_to_environment()

            env_vars = self.env_manager.load_env()
            host = env_vars.get("API_HOST", "0.0.0.0")
            port = env_vars.get("API_PORT", "8081")

            if daemon:
                success = pm.start_daemon(host=host, port=int(port))
                if success:
                    self.printer.success(f"服务已在后台启动 (http://{host}:{port})")
                    return True
                else:
                    self.printer.error("后台启动失败，请查看日志")
                    return False
            else:
                self.printer.print()
                self.printer.print(f"服务将在前台启动: http://{host}:{port}")
                self.printer.print("按 Ctrl+C 停止服务")
                self.printer.print()
                pm.start_foreground(host=host, port=int(port))
                return True

        except Exception as e:
            self.printer.error(f"启动失败: {e}")
            self.printer.print("可手动运行: anexus start")
            return False

    # ─── 完成总结 ──────────────────────────────────────────────────────

    def _show_summary(self, channels: List[str], started: bool = False) -> None:
        """显示配置完成摘要"""
        self.printer.print()
        self.printer.print(self.printer._colorize(
            "╔══════════════════════════════════════════════════════╗", "green"))
        self.printer.print(self.printer._colorize(
            "║           🎉  Onboard 配置完成！                     ║", "green"))
        self.printer.print(self.printer._colorize(
            "╚══════════════════════════════════════════════════════╝", "green"))
        self.printer.print()

        # 显示已配置的 Channel
        if channels:
            self.printer.print(self.printer._colorize("已配置的 Channel:", "bold"))
            for name in channels:
                ch = CHANNEL_REGISTRY.get(name, {})
                self.printer.list_item(f"{ch.get('display', name)}")
        else:
            self.printer.print(self.printer._colorize("未配置 Channel", "dim"))

        self.printer.print()

        # Provider
        env_vars = self.env_manager.load_env()
        provider = env_vars.get("DEFAULT_PROVIDER", "codebuddy")
        self.printer.key_value("默认 Provider", provider)

        # 服务地址
        host = env_vars.get("API_HOST", "0.0.0.0")
        port = env_vars.get("API_PORT", "8081")
        self.printer.key_value("服务地址", f"http://{host}:{port}")

        self.printer.print()

        if not started:
            self.printer.print(self.printer._colorize("下一步操作:", "bold"))
            self.printer.list_item("运行 'anexus start' 启动服务")
            self.printer.list_item("运行 'anexus status' 查看服务和 Channel 状态")
            self.printer.list_item("运行 'anexus config show' 查看完整配置")
            self.printer.list_item("运行 'anexus config wizard --section channels' 修改 Channel 配置")
            self.printer.print()

    # ─── 工具方法 ──────────────────────────────────────────────────────

    def _multi_select(self, message: str, options: List[str]) -> List[int]:
        """多选交互（输入逗号分隔的编号）

        Returns:
            选中的索引列表
        """
        self.printer.print(self.printer._colorize(message, "cyan"))

        for i, option in enumerate(options):
            self.printer.print(f"  {i + 1}. {option}")

        self.printer.print()

        try:
            response = input(
                self.printer._colorize(
                    f"请输入编号 [1-{len(options)}]（逗号分隔，如 1,3 ；a=全选；Enter=跳过）: ",
                    "yellow",
                )
            ).strip()

            if not response:
                return []

            if response.lower() == "a":
                return list(range(len(options)))

            indices = []
            for part in response.split(","):
                part = part.strip()
                if part.isdigit():
                    idx = int(part) - 1
                    if 0 <= idx < len(options):
                        indices.append(idx)
                # 支持范围 e.g. 1-3
                elif "-" in part:
                    try:
                        start, end = part.split("-", 1)
                        for i in range(int(start) - 1, int(end)):
                            if 0 <= i < len(options):
                                indices.append(i)
                    except ValueError:
                        pass

            return sorted(set(indices))

        except (EOFError, KeyboardInterrupt):
            self.printer.print()
            return []

    def _mask_token(self, token: str) -> str:
        """遮盖 Token 的中间部分"""
        if len(token) <= 8:
            return "****"
        return token[:4] + "****" + token[-4:]

    def _detect_package_manager(self) -> str:
        """检测包管理器 (uv 或 pip)"""
        if (self.base_dir / "uv.lock").exists():
            try:
                result = subprocess.run(
                    ["uv", "--version"], capture_output=True, text=True
                )
                if result.returncode == 0:
                    return "uv"
            except FileNotFoundError:
                pass
        return "pip"
