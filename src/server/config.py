# -*- coding: utf-8 -*-
"""服务器配置管理"""

from pydantic_settings import BaseSettings


class ServerSettings(BaseSettings):
    """通用服务器与运行时配置"""

    # API 配置
    api_host: str = "0.0.0.0"
    api_port: int = 8081
    api_workers: int = 1

    # 日志配置
    log_level: str = "INFO"
    log_dir: str = "./logs"
    log_max_bytes: int = 10485760
    log_backup_count: int = 5

    # 流式配置
    stream_chunk_size: int = 100
    stream_delay_ms: int = 50
    stream_buffer_size: int = 1000

    # response_url 回调
    response_url_callback_enabled: bool = False
    response_url_stream_timeout_seconds: float = 25.0
    response_url_stream_progress_notices: int = 2

    # 调试 / 环境
    debug: bool = False
    environment: str = "development"
    cors_origins: str = "*"
    rate_limit_enabled: bool = True  # zero-dep token-bucket limiter on login + chat
    ssrf_protection_enabled: bool = True

    # 用户与工作目录
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

    # 执行器配置
    executor_enabled: bool = True
    executor_default_max_concurrency: int = 3
    executor_poll_interval: float = 1.0
    executor_max_retries: int = 3
    executor_retry_delay: float = 5.0
    executor_task_timeout: float = 3600.0

    # Persistent CLI
    persistent_enabled: bool = False
    persistent_idle_timeout: float = 1800.0
    persistent_quiescence_timeout: float = 3.0
    persistent_max_sessions_per_user: int = 5
    persistent_init_timeout: float = 60.0

    # Scheduler
    scheduler_enabled: bool = True
    scheduler_poll_interval: float = 15.0

    # Hook profile
    hook_profile_default: str = "standard"
    hook_enable_pre_checks: bool = True
    hook_enable_post_audit: bool = True

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }


class ProviderSettings(BaseSettings):
    """Provider 与 CLI 配置"""

    cli_command: str = "codebuddy"
    cli_timeout: int = 600
    agent_cli_command_map: dict = {}

    codebuddy_default_model: str = ""
    hermes_command: str = "hermes"
    hermes_default_model: str = ""

    default_provider: str = "claude"
    default_alias: str = ""
    default_exec_user: str = ""

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }


class NexusSettings(BaseSettings):
    """Nexus 控制台配置"""

    nexus_password: str | None = None
    nexus_auth_token: str | None = None
    nexus_session_ttl: int = 86400

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }


class Settings(ServerSettings, ProviderSettings, NexusSettings):
    """完整配置（仅保留核心运行所需设置）"""

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }


settings = Settings()
