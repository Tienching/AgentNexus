# -*- coding: utf-8 -*-
"""服务器配置管理"""

from pydantic_settings import BaseSettings


class ServerSettings(BaseSettings):
    """通用服务器配置"""

    # API 配置
    api_host: str = "0.0.0.0"
    api_port: int = 8081
    api_workers: int = 1

    # 日志配置
    log_level: str = "INFO"
    log_dir: str = "./logs"
    log_max_bytes: int = 10485760  # 10MB
    log_backup_count: int = 5

    # 流式配置
    stream_chunk_size: int = 100  # 每次发送的字符数
    stream_delay_ms: int = 50  # 发送间隔毫秒数
    stream_buffer_size: int = 1000  # 缓冲区大小

    # 调试模式
    debug: bool = False

    # 环境
    environment: str = "development"

    # 用户目录配置
    user_home_base: str = "/home"
    auto_create_user_dir: bool = True
    exec_user: str = "ubuntu"

    # Redis 配置
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None
    redis_key_prefix: str = "aona:"
    redis_connection_timeout: int = 10
    redis_socket_timeout: int = 5
    
    # 任务执行器配置
    executor_enabled: bool = True
    executor_default_max_concurrency: int = 3
    executor_poll_interval: float = 1.0
    executor_max_retries: int = 3
    executor_retry_delay: float = 5.0
    executor_task_timeout: float = 3600.0

    # Scheduler configuration
    scheduler_enabled: bool = True
    scheduler_poll_interval: float = 15.0  # seconds between schedule checks
    
    # Channel 服务配置
    channels_enabled: bool = True
    
    # Telegram 配置
    telegram_bot_token: str | None = None
    telegram_allowed_users: str = ""  # 逗号分隔的用户 ID
    
    # Slack 配置
    slack_bot_token: str | None = None
    slack_app_token: str | None = None
    
    # Discord 配置
    discord_bot_token: str | None = None
    
    # 飞书 (Feishu) 配置
    feishu_app_id: str | None = None
    feishu_app_secret: str | None = None
    feishu_verification_token: str | None = None
    feishu_encrypt_key: str | None = None
    feishu_domain: str = "feishu"  # "feishu" 或 "lark"
    
    # WhatsApp 配置
    whatsapp_bridge_url: str | None = None
    whatsapp_bridge_auth_token: str | None = None
    whatsapp_session_name: str = "default"
    
    # Signal 配置
    signal_api_url: str = "http://localhost:8081"
    signal_phone_number: str | None = None

    # 企业微信智能机器人 (WeCom AI Bot) 配置
    wecom_mode: str = "webhook"  # API 模式：webhook | websocket
    wecom_token: str | None = None  # 回调配置的 Token（Webhook 模式）
    wecom_encoding_aes_key: str | None = None  # 回调配置的 EncodingAESKey（Webhook 模式）
    wecom_aibot_id: str | None = None  # 智能机器人 ID（可选）
    wecom_ai_bot_id: str | None = None  # 智能机器人 BotID（WebSocket 模式）
    wecom_secret: str | None = None  # 长连接专用 Secret（WebSocket 模式）
    wecom_ws_url: str = "wss://openws.work.weixin.qq.com"  # WebSocket 连接地址
    wecom_heartbeat_interval: int = 30  # 心跳间隔（秒）
    wecom_reconnect_max_attempts: int = 20  # 最大重连次数
    wecom_reconnect_base_delay: float = 5.0  # 重连基础延迟（秒）
    wecom_reconnect_max_delay: float = 60.0  # 重连最大延迟（秒）
    wecom_ws_stream_interval_ms: int = 500  # WS 流式更新间隔（毫秒）

    # 企业微信普通机器人 (WeCom Bot) 配置
    wecom_bot_token: str | None = None  # 回调配置的 Token
    wecom_bot_encoding_aes_key: str | None = None  # 回调配置的 EncodingAESKey
    wecom_bot_webhook_key: str | None = None  # Webhook Key（必填，单聊/群聊发送）
    wecom_bot_stream_chunk_size: int = 50  # 流式模拟每次发送字符数（群聊生效）
    wecom_bot_stream_interval_ms: int = 200  # 流式模拟发送间隔 ms（群聊生效）
    wecom_bot_cli_timeout: int = 1800  # 企微普通机器人 CLI 超时（秒），避免交互/慢任务过早超时

    # Channel-level provider/alias/exec_user overrides
    # Format: <CHANNEL>_PROVIDER / <CHANNEL>_ALIAS / <CHANNEL>_EXEC_USER
    # When set, the channel will use the specified provider/alias/exec_user
    # instead of global defaults. Session-level /switch still takes priority.
    telegram_provider: str | None = None
    telegram_alias: str | None = None
    telegram_exec_user: str | None = None
    slack_provider: str | None = None
    slack_alias: str | None = None
    slack_exec_user: str | None = None
    discord_provider: str | None = None
    discord_alias: str | None = None
    discord_exec_user: str | None = None
    feishu_provider: str | None = None
    feishu_alias: str | None = None
    feishu_exec_user: str | None = None
    wecom_provider: str | None = None
    wecom_alias: str | None = None
    wecom_exec_user: str | None = None
    wecom_bot_provider: str | None = None
    wecom_bot_alias: str | None = None
    wecom_bot_exec_user: str | None = None

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False
    }


class ProviderSettings(BaseSettings):
    """Provider 特定配置"""

    # CLI Executor 配置（服务于所有 Provider）
    cli_command: str = "codebuddy"
    cli_timeout: int = 600
    agent_cli_command_map: dict = {}

    # Gemini CLI 配置
    gemini_command: str = "gemini"
    
    # 默认 Provider 和 Exec User
    default_provider: str = "codebuddy"
    default_alias: str = ""
    default_exec_user: str = ""

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False
    }


class NexusSettings(BaseSettings):
    """Nexus 控制台配置"""
    
    # Nexus 登录密码（为空则禁用认证）
    nexus_password: str | None = None
    
    # Session 有效期（秒）
    nexus_session_ttl: int = 86400  # 24 小时
    
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False
    }


# 合并配置
class Settings(ServerSettings, ProviderSettings, NexusSettings):
    """完整配置（包含服务器和 Provider 配置）"""
    pass


# 全局配置实例
settings = Settings()
