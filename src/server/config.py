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
    
    # WhatsApp 配置
    whatsapp_bridge_url: str | None = None
    whatsapp_bridge_auth_token: str | None = None
    whatsapp_session_name: str = "default"
    
    # Signal 配置
    signal_api_url: str = "http://localhost:8081"
    signal_phone_number: str | None = None

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False
    }


class ProviderSettings(BaseSettings):
    """Provider 特定配置"""

    # CLI Executor 配置（服务于所有 Provider）
    cli_command: str = "claude"
    cli_timeout: int = 120
    agent_cli_command_map: dict = {}

    # Gemini CLI 配置
    gemini_command: str = "gemini"
    
    # 默认 Provider 和 Exec User
    default_provider: str = "claude"
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
