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

    # Redis 配置
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None
    redis_key_prefix: str = "aona:"  # Redis key 前缀
    redis_connection_timeout: int = 10  # 连接超时（秒）
    redis_socket_timeout: int = 5  # 操作超时（秒）
    
    # 任务执行器配置
    executor_enabled: bool = True  # 是否启用任务执行器
    executor_default_max_concurrency: int = 1  # 默认最大并行数
    executor_poll_interval: float = 1.0  # 轮询间隔（秒）
    executor_max_retries: int = 3  # 最大重试次数
    executor_retry_delay: float = 5.0  # 重试延迟（秒）
    executor_task_timeout: float = 3600.0  # 任务超时（秒）

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False
    }


# 创建全局配置实例
settings = Settings()
