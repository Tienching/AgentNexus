"""通道配置定义"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ChannelType(str, Enum):
    """支持的通道类型"""
    TELEGRAM = "telegram"
    SLACK = "slack"
    DISCORD = "discord"
    WHATSAPP = "whatsapp"
    SIGNAL = "signal"
    FEISHU = "feishu"


@dataclass
class ChannelConfig:
    """
    通道配置基类

    Attributes:
        type: 通道类型
        enabled: 是否启用
        name: 通道名称（用于标识）
        allowed_users: 允许访问的用户 ID 列表（空列表表示允许所有）
        blocked_users: 禁止访问的用户 ID 列表
        rate_limit: 速率限制（每分钟消息数，0 表示无限制）
        extra: 额外配置参数
    """
    type: ChannelType
    enabled: bool = True
    name: str = ""
    allowed_users: List[str] = field(default_factory=list)
    blocked_users: List[str] = field(default_factory=list)
    rate_limit: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """后处理"""
        if isinstance(self.type, str):
            self.type = ChannelType(self.type)
        if not self.name:
            self.name = self.type.value


@dataclass
class TelegramConfig(ChannelConfig):
    """Telegram 配置"""
    type: ChannelType = ChannelType.TELEGRAM
    bot_token: str = ""
    webhook_url: Optional[str] = None  # 如果使用 Webhook 模式
    webhook_secret: Optional[str] = None
    allowed_updates: List[str] = field(default_factory=lambda: ["message", "callback_query"])
    skip_pending: bool = True  # 启动时跳过积压消息
    connect_timeout: float = 30.0
    read_timeout: float = 30.0

    def __post_init__(self):
        super().__post_init__()
        if not self.bot_token:
            raise ValueError("Telegram bot_token is required")


@dataclass
class SlackConfig(ChannelConfig):
    """Slack 配置"""
    type: ChannelType = ChannelType.SLACK
    bot_token: str = ""  # xoxb-...
    app_token: Optional[str] = None  # xapp-... (Socket Mode 需要)
    signing_secret: Optional[str] = None  # HTTP 模式需要
    socket_mode: bool = True  # True: Socket Mode, False: HTTP Webhook
    webhook_path: str = "/slack/events"
    bot_user_id: Optional[str] = None

    def __post_init__(self):
        super().__post_init__()
        if not self.bot_token:
            raise ValueError("Slack bot_token is required")
        if self.socket_mode and not self.app_token:
            raise ValueError("Slack Socket Mode requires app_token")
        if not self.socket_mode and not self.signing_secret:
            raise ValueError("Slack HTTP Mode requires signing_secret")


@dataclass
class DiscordConfig(ChannelConfig):
    """Discord 配置"""
    type: ChannelType = ChannelType.DISCORD
    bot_token: str = ""
    intents: List[str] = field(default_factory=lambda: [
        "guilds", "guild_messages", "direct_messages", "message_content"
    ])
    command_prefix: str = "!"
    sync_commands: bool = True
    activity_name: Optional[str] = None
    activity_type: Optional[str] = None  # playing, listening, watching, competing

    def __post_init__(self):
        super().__post_init__()
        if not self.bot_token:
            raise ValueError("Discord bot_token is required")


@dataclass
class WhatsAppConfig(ChannelConfig):
    """WhatsApp 配置"""
    type: ChannelType = ChannelType.WHATSAPP
    bridge_url: str = "ws://localhost:3000"  # Node.js Bridge WebSocket URL
    bridge_auth_token: Optional[str] = None
    session_name: str = "default"
    auto_reconnect: bool = True
    reconnect_interval: float = 5.0
    max_reconnect_attempts: int = 10

    def __post_init__(self):
        super().__post_init__()
        if not self.bridge_url:
            raise ValueError("WhatsApp bridge_url is required")


@dataclass
class SignalConfig(ChannelConfig):
    """Signal 配置"""
    type: ChannelType = ChannelType.SIGNAL
    api_url: str = "http://localhost:8081"  # signal-cli REST API URL
    phone_number: str = ""  # 绑定的电话号码 (+1234567890)
    account: Optional[str] = None  # 账号别名
    auto_receive: bool = True  # 自动接收消息
    receive_interval: float = 1.0  # 轮询间隔（秒）

    def __post_init__(self):
        super().__post_init__()
        if not self.phone_number:
            raise ValueError("Signal phone_number is required")


@dataclass
class FeishuConfig(ChannelConfig):
    """飞书 (Feishu/Lark) 配置"""
    type: ChannelType = ChannelType.FEISHU
    app_id: str = ""  # 飞书应用 App ID
    app_secret: str = ""  # 飞书应用 App Secret
    verification_token: Optional[str] = None  # Webhook 验证令牌
    encrypt_key: Optional[str] = None  # 事件加密密钥
    domain: str = "feishu"  # "feishu" (中国) 或 "lark" (国际)

    def __post_init__(self):
        super().__post_init__()
        if not self.app_id:
            raise ValueError("Feishu app_id is required")
        if not self.app_secret:
            raise ValueError("Feishu app_secret is required")


# 配置类型映射
CONFIG_MAP = {
    ChannelType.TELEGRAM: TelegramConfig,
    ChannelType.SLACK: SlackConfig,
    ChannelType.DISCORD: DiscordConfig,
    ChannelType.WHATSAPP: WhatsAppConfig,
    ChannelType.SIGNAL: SignalConfig,
    ChannelType.FEISHU: FeishuConfig,
}


def create_config(type_: ChannelType, **kwargs) -> ChannelConfig:
    """创建配置实例"""
    config_class = CONFIG_MAP.get(type_)
    if not config_class:
        raise ValueError(f"Unknown channel type: {type_}")
    return config_class(**kwargs)
