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

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False
    }


class ProviderSettings(BaseSettings):
    """Provider 特定配置"""

    # CCR (Claude Code Runner) 配置
    ccr_command: str = "claude"
    ccr_timeout: int = 120
    agent_ccr_command_map: dict = {}

    # Gemini CLI 配置
    gemini_command: str = "gemini"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False
    }


# 合并配置（向后兼容）
class Settings(ServerSettings, ProviderSettings):
    """完整配置（包含服务器和 Provider 配置）"""
    pass


# 全局配置实例
settings = Settings()
