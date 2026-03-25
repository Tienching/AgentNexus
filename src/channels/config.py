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
    WECOM = "wecom"
    WECOM_BOT = "wecom_bot"
    WECHAT = "wechat"


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

    # Channel-level AI provider overrides (optional)
    # When set, these take priority over global defaults but are
    # overridden by session-level /switch commands.
    provider: Optional[str] = None   # e.g. "claude", "gemini", "codebuddy"
    alias: Optional[str] = None      # e.g. "claude-internal"
    exec_user: Optional[str] = None  # e.g. "ubuntu", "tswitch"

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


@dataclass
class WeComConfig(ChannelConfig):
    """企业微信智能机器人 (WeCom AI Bot) 配置

    支持两种 API 模式（通过 mode 字段选择）：

    Webhook 模式（默认）：
    - 必填：token + encoding_aes_key
    - 通过 HTTP 回调接收消息
    - 支持被动回复（加密 JSON）和 response_url 主动回复

    WebSocket 长连接模式：
    - 必填：bot_id + secret
    - 通过 wss://openws.work.weixin.qq.com 长连接收发消息
    - 支持原生流式消息（stream.id + finish）
    - 无需加解密，无需公网 IP

    参考文档: https://developer.work.weixin.qq.com/document/path/101039
    """
    type: ChannelType = ChannelType.WECOM
    mode: str = "webhook"
    token: str = ""  # 回调配置的 Token（Webhook 模式）
    encoding_aes_key: str = ""  # 回调配置的 EncodingAESKey（Webhook 模式）
    aibot_id: Optional[str] = None  # 智能机器人 ID（可选，用于过滤）
    bot_id: str = ""  # 智能机器人 BotID（WebSocket 模式）
    secret: str = ""  # 长连接专用 Secret（WebSocket 模式）
    ws_url: str = "wss://openws.work.weixin.qq.com"  # WebSocket 连接地址
    heartbeat_interval: int = 30  # 心跳间隔（秒）
    reconnect_max_attempts: int = 20  # 最大重连次数
    reconnect_base_delay: float = 5.0  # 重连基础延迟（秒）
    reconnect_max_delay: float = 60.0  # 重连最大延迟（秒）
    ws_stream_interval_ms: int = 500  # WS 流式更新间隔（毫秒）
    ws_stream_soft_limit_seconds: int = 330  # 单段 stream.id 软截止（秒）
    ws_stream_hard_limit_seconds: int = 350  # 单段 stream.id 硬截止（秒）

    def __post_init__(self):
        super().__post_init__()
        if self.mode == "webhook":
            if not self.token:
                raise ValueError("WeCom webhook mode requires token")
            if not self.encoding_aes_key:
                raise ValueError("WeCom webhook mode requires encoding_aes_key")
        elif self.mode == "websocket":
            if not self.bot_id:
                raise ValueError("WeCom websocket mode requires bot_id")
            if not self.secret:
                raise ValueError("WeCom websocket mode requires secret")
        else:
            raise ValueError(f"Invalid WeCom mode: {self.mode}, must be 'webhook' or 'websocket'")


@dataclass
class WeComBotConfig(ChannelConfig):
    """企业微信普通机器人 (WeCom Bot) 配置

    必填：token + encoding_aes_key + webhook_key（从 Webhook 地址中提取 key）

    发送策略：
    - 单聊 → webhook/send 一次性发送完整回复
    - 群聊 → webhook/send 多次发送模拟流式（受 20条/分钟 限制）

    参考文档:
    - 主动消息通告(webhook): https://developer.work.weixin.qq.com/document/path/99110
    """
    type: ChannelType = ChannelType.WECOM_BOT
    token: str = ""  # 回调配置的 Token（接收消息用）
    encoding_aes_key: str = ""  # 回调配置的 EncodingAESKey（43 字符）

    # Webhook 参数（必填，从 Webhook 地址中提取 key=xxx）
    webhook_key: str = ""  # Webhook URL 中的 key 参数

    # 流式模拟配置（群聊生效）
    stream_chunk_size: int = 50  # 每次发送的增量字符数
    stream_interval_ms: int = 200  # 增量发送间隔（毫秒）

    def __post_init__(self):
        super().__post_init__()
        if not self.token:
            raise ValueError("WeCom Bot token is required")
        if not self.encoding_aes_key:
            raise ValueError("WeCom Bot encoding_aes_key is required")
        if not self.webhook_key:
            raise ValueError("WeCom Bot webhook_key is required")


@dataclass
class WeChatConfig(ChannelConfig):
    """微信个人号 (WeChat Personal via iLink Bot API) 配置

    通过 iLink Bot API 接入微信个人号，使用 HTTP JSON + Long-Polling 模式收发消息。

    必填：bot_token（通过扫码登录获取）

    参考文档: https://github.com/nicepkg/openclaw-weixin (openclaw-weixin plugin)
    """
    type: ChannelType = ChannelType.WECHAT
    bot_token: str = ""  # iLink bot token（扫码登录后获取）
    base_url: str = "https://ilinkai.weixin.qq.com"  # API 基础 URL
    poll_timeout_ms: int = 35000  # getUpdates 长轮询超时（毫秒）
    api_timeout_ms: int = 15000  # 普通 API 请求超时（毫秒）
    reconnect_max_attempts: int = 20  # 最大重连次数
    reconnect_base_delay: float = 5.0  # 重连基础延迟（秒）
    reconnect_max_delay: float = 60.0  # 重连最大延迟（秒）
    sync_buf_path: str = ""  # get_updates_buf 持久化路径（空则用默认）

    def __post_init__(self):
        super().__post_init__()
        if not self.bot_token:
            raise ValueError("WeChat bot_token is required")


# 配置类型映射
CONFIG_MAP = {
    ChannelType.TELEGRAM: TelegramConfig,
    ChannelType.SLACK: SlackConfig,
    ChannelType.DISCORD: DiscordConfig,
    ChannelType.WHATSAPP: WhatsAppConfig,
    ChannelType.SIGNAL: SignalConfig,
    ChannelType.FEISHU: FeishuConfig,
    ChannelType.WECOM: WeComConfig,
    ChannelType.WECOM_BOT: WeComBotConfig,
    ChannelType.WECHAT: WeChatConfig,
}


def create_config(type_: ChannelType, **kwargs) -> ChannelConfig:
    """创建配置实例"""
    config_class = CONFIG_MAP.get(type_)
    if not config_class:
        raise ValueError(f"Unknown channel type: {type_}")
    return config_class(**kwargs)
