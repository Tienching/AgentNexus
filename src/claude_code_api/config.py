"""配置管理"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用配置"""

    # API 配置
    api_host: str = "0.0.0.0"
    api_port: int = 8081
    api_workers: int = 1

    # CCR 配置
    ccr_command: str = "claude-internal"  # ccr / claude-internal / codebuddy-code
    ccr_timeout: int = 120  # 秒
    agent_ccr_command_map: dict = {}

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
    user_home_base: str = "/home"  # 用户主目录基础路径（使用/home/{agent_name}/sessions/{session_id}结构）
    auto_create_user_dir: bool = True   # 是否自动创建用户目录

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False
    }


# 创建全局配置实例
settings = Settings()
