"""日志配置模块"""

import logging
import logging.handlers
import json
from datetime import datetime
import os
import sys
from typing import Any, Dict, Optional
import uuid
from contextvars import ContextVar
import traceback
from datetime import timezone

# 用于存储请求上下文的变量
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


class HumanReadableFormatter(logging.Formatter):
    """人类可读的日志格式化器，用于开发环境"""

    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录为人类可读格式"""
        # 获取基本信息
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        level = record.levelname
        correlation_id = correlation_id_var.get()

        # 根据级别设置颜色
        color_codes = {
            "DEBUG": "\033[36m",  # Cyan
            "INFO": "\033[32m",   # Green
            "WARNING": "\033[33m", # Yellow
            "ERROR": "\033[31m",   # Red
            "CRITICAL": "\033[35m", # Magenta
        }
        reset_code = "\033[0m"
        color = color_codes.get(level, "")

        # 构建基础消息
        base_msg = f"{color}[{timestamp}] {level:8}{reset_code} | {record.getMessage()}"

        # 添加correlation_id（如果存在）
        if correlation_id:
            base_msg += f" | ID: {correlation_id[:8]}"

        # 添加请求类型标识
        if hasattr(record, "request_type"):
            if record.request_type == "incoming":
                base_msg = "→ " + base_msg
            elif record.request_type == "response":
                base_msg = "← " + base_msg

        # 添加关键额外字段
        important_fields = []
        if hasattr(record, "duration_ms"):
            important_fields.append(f"duration={record.duration_ms}ms")
        if hasattr(record, "status_code"):
            important_fields.append(f"status={record.status_code}")
        if hasattr(record, "user"):
            important_fields.append(f"user={record.user}")
        if hasattr(record, "path"):
            important_fields.append(f"path={record.path}")

        if important_fields:
            base_msg += f" | {' '.join(important_fields)}"

        # 添加请求/响应体预览（如果存在）
        if hasattr(record, "request_body"):
            body = record.request_body
            if isinstance(body, (dict, list)):
                body_str = json.dumps(body, ensure_ascii=False)[:200]
            else:
                body_str = str(body)[:200]
            base_msg += f"\n    Request Body: {body_str}"

        if hasattr(record, "response_body"):
            body = record.response_body
            if isinstance(body, (dict, list)):
                body_str = json.dumps(body, ensure_ascii=False)[:200]
            else:
                body_str = str(body)[:200]
            base_msg += f"\n    Response Body: {body_str}"

        # 添加异常信息（如果有）
        if record.exc_info:
            base_msg += f"\n{color}Exception:{reset_code}\n"
            base_msg += self.formatException(record.exc_info)

        return base_msg


class JsonFormatter(logging.Formatter):
    """自定义JSON格式化器"""

    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录为JSON"""
        # 基础日志对象
        log_obj: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # 添加correlation_id（如果存在）
        correlation_id = correlation_id_var.get()
        if correlation_id:
            log_obj["correlation_id"] = correlation_id

        # 添加所有额外字段（通过extra传入的）
        for key, value in record.__dict__.items():
            # 只跳过已经在基础log_obj中的字段，保留所有其他字段
            if key not in log_obj and key not in ["exc_info", "exc_text", "stack_info"]:
                log_obj[key] = value

        # 添加异常信息（如果有）
        if record.exc_info:
            log_obj["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": self.formatException(record.exc_info)
            }

        return json.dumps(log_obj, ensure_ascii=False, default=str)


def setup_logger(
    log_level: str = "INFO",
    log_dir: str = "./logs",
    log_max_bytes: int = 10485760,
    log_backup_count: int = 5,
    use_human_readable: bool = False,
) -> None:
    """
    配置日志系统

    Args:
        log_level: 日志级别
        log_dir: 日志目录
        log_max_bytes: 单个日志文件最大字节数
        log_backup_count: 保留的日志文件数量
        use_human_readable: 是否在控制台使用人类可读格式
    """
    # 创建日志目录
    os.makedirs(log_dir, exist_ok=True)

    # 获取根日志器
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, log_level.upper()))

    # 清除现有处理器
    logger.handlers.clear()

    # 文件处理器（JSON格式，带轮转）
    file_handler = logging.handlers.RotatingFileHandler(
        filename=os.path.join(log_dir, "api.log"),
        maxBytes=log_max_bytes,
        backupCount=log_backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(JsonFormatter())
    file_handler.setLevel(logging.DEBUG)

    # 错误日志文件处理器
    error_file_handler = logging.handlers.RotatingFileHandler(
        filename=os.path.join(log_dir, "error.log"),
        maxBytes=log_max_bytes,
        backupCount=log_backup_count,
        encoding="utf-8",
    )
    error_file_handler.setFormatter(JsonFormatter())
    error_file_handler.setLevel(logging.ERROR)

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    if use_human_readable:
        # 使用人类可读格式（开发环境）
        console_handler.setFormatter(HumanReadableFormatter())
    else:
        # 使用简洁格式（生产环境）
        console_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        console_handler.setFormatter(console_formatter)
    console_handler.setLevel(getattr(logging, log_level.upper()))

    # 添加处理器到日志器
    logger.addHandler(file_handler)
    logger.addHandler(error_file_handler)
    logger.addHandler(console_handler)

    # 设置第三方库日志级别
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    获取指定名称的日志器

    Args:
        name: 日志器名称

    Returns:
        Logger实例
    """
    return logging.getLogger(name)


def generate_correlation_id() -> str:
    """生成唯一的关联ID"""
    return str(uuid.uuid4())


def set_correlation_id(correlation_id: str) -> None:
    """设置当前请求的关联ID"""
    correlation_id_var.set(correlation_id)


def get_correlation_id() -> str:
    """获取当前请求的关联ID"""
    return correlation_id_var.get()


class RequestLogger:
    """请求日志记录器，提供结构化的请求/响应日志"""

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.start_time = None
        self.request_data = {}

    def log_request(
        self,
        method: str,
        path: str,
        headers: Dict[str, str],
        body: Optional[Any] = None,
        query_params: Optional[Dict[str, str]] = None,
        client_info: Optional[str] = None,
    ) -> None:
        """记录完整的请求信息"""
        self.start_time = datetime.now(timezone.utc)

        # 准备请求数据
        self.request_data = {
            "method": method,
            "path": path,
            "client": client_info,
            "query_params": query_params or {},
        }

        # 处理请求头（移除敏感信息）
        safe_headers = self._sanitize_headers(headers)
        self.request_data["headers"] = safe_headers

        # 处理请求体
        if body is not None:
            body_info = self._process_body(body)
            self.request_data.update(body_info)

        # 记录请求
        self.logger.info(
            f"→ REQUEST: {method} {path}",
            extra={
                "request_type": "incoming",
                **self.request_data
            }
        )

    def log_response(
        self,
        status_code: int,
        response_body: Optional[Any] = None,
        error: Optional[Exception] = None,
    ) -> None:
        """记录响应信息"""
        if self.start_time:
            duration_ms = int((datetime.now(timezone.utc) - self.start_time).total_seconds() * 1000)
        else:
            duration_ms = 0

        response_data = {
            "status_code": status_code,
            "duration_ms": duration_ms,
            "request_type": "response",
        }

        # 添加请求摘要
        if self.request_data:
            response_data["request_summary"] = {
                "method": self.request_data.get("method"),
                "path": self.request_data.get("path"),
            }

        # 处理响应体
        if response_body is not None:
            body_info = self._process_body(response_body, is_response=True)
            response_data.update(body_info)

        # 处理错误
        if error:
            response_data["error"] = {
                "type": type(error).__name__,
                "message": str(error),
            }
            if hasattr(error, "__traceback__"):
                response_data["error"]["traceback"] = traceback.format_tb(error.__traceback__)

        # 选择日志级别
        if status_code >= 500:
            log_level = self.logger.error
            symbol = "✗"
        elif status_code >= 400:
            log_level = self.logger.warning
            symbol = "⚠"
        else:
            log_level = self.logger.info
            symbol = "✓"

        # 记录响应
        log_level(
            f"← RESPONSE: {status_code} {symbol} ({duration_ms}ms)",
            extra=response_data
        )

    def _sanitize_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        """清理请求头，移除敏感信息"""
        sensitive_headers = {
            "authorization", "x-api-key", "x-auth-token",
            "cookie", "set-cookie", "x-csrf-token"
        }

        safe_headers = {}
        for key, value in headers.items():
            key_lower = key.lower()
            if key_lower in sensitive_headers:
                safe_headers[key] = "***REDACTED***"
            elif len(value) > 500:  # 截断超长的头
                safe_headers[key] = value[:500] + f"...[truncated, total: {len(value)} chars]"
            else:
                safe_headers[key] = value

        return safe_headers

    def _process_body(self, body: Any, is_response: bool = False) -> Dict[str, Any]:
        """处理请求/响应体"""
        prefix = "response" if is_response else "request"
        result = {}

        if body is None:
            return {f"{prefix}_body": None}

        # 处理字符串
        if isinstance(body, str):
            if len(body) > 10000:
                result[f"{prefix}_body"] = body[:10000]
                result[f"{prefix}_body_truncated"] = True
                result[f"{prefix}_body_size"] = len(body)
            else:
                result[f"{prefix}_body"] = body
                result[f"{prefix}_body_size"] = len(body)

        # 处理字典/列表（JSON数据）
        elif isinstance(body, (dict, list)):
            body_str = json.dumps(body, ensure_ascii=False, default=str)
            result[f"{prefix}_body"] = body
            result[f"{prefix}_body_size"] = len(body_str)

        # 处理字节
        elif isinstance(body, bytes):
            try:
                body_str = body.decode('utf-8')
                return self._process_body(body_str, is_response)
            except:
                result[f"{prefix}_body"] = f"<binary data: {len(body)} bytes>"
                result[f"{prefix}_body_size"] = len(body)

        else:
            result[f"{prefix}_body"] = str(body)[:1000]
            result[f"{prefix}_body_type"] = type(body).__name__

        return result