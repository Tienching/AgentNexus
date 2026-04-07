# -*- coding: utf-8 -*-
"""易事厅格式数据模型定义"""

from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional


class RequestModel(BaseModel):
    """Legacy 请求体模型（宽松模式）"""

    user: Optional[str] = Field(None, description="用户名")
    msg_type: Optional[str] = Field(default="text", description="消息类型，目前只回调text类型")
    content: str = Field(..., description="用户消息文本内容")
    msg_id: Optional[str] = Field(default="", description="用户消息ID，异步模式回调发送消息需要回传该值")
    raw_msg: Optional[str] = Field(default="", description="解密后的消息回调")
    session_id: Optional[str] = Field(default="", description="助手号场景的会话id，其他场景忽略")
    business_keys: Optional[List[str]] = Field(default_factory=list, description="服务标识")
    response_url: Optional[str] = Field(default="", description="流式连接断开后的回调URL，用于发送剩余消息")
    image_paths: Optional[List[str]] = Field(default_factory=list, description="本地图片文件路径列表（由 media_downloader 下载后填充）")
    file_paths: Optional[List[str]] = Field(default_factory=list, description="本地文件路径列表（由 media_downloader 下载后填充）")
    content_parts: Optional[list] = Field(default_factory=list, description="有序内容部件列表，保留图文交错顺序。每项为 {'type':'text','content':'...'} 或 {'type':'image','path':'...'}")

    model_config = ConfigDict(extra="allow")


class Document(BaseModel):
    """召回文档模型"""

    doc_id: str = Field(..., description="文档ID")
    space_id: str = Field(..., description="空间ID")
    title: str = Field(..., description="标题")
    url: str = Field(..., description="文档URL")
    score: float = Field(..., description="相关度分数")


class GlobalOutput(BaseModel):
    """全局输出模型"""

    context: str = Field(default="", description="上下文信息")
    answer_success: int = Field(default=0, description="回答成功标识，1表示成功")
    docs: List[Document] = Field(default_factory=list, description="召回的文档列表")


class StreamResponse(BaseModel):
    """流式响应模型"""

    response: str = Field(..., description="响应文本内容")
    finished: bool = Field(..., description="是否结束")
    global_output: GlobalOutput = Field(..., description="全局输出信息")


class HealthCheck(BaseModel):
    """Single subsystem health check result.

    Ported from mission-control performHealthCheck (commits 4eda03a / afa8e9d).
    """
    name: str
    status: str  # "healthy" | "warning" | "degraded" | "unhealthy" | "error"
    message: str = ""
    detail: Optional[dict] = None


class HealthResponse(BaseModel):
    """健康检查响应 — enhanced with structured checks.

    Ported from mission-control performHealthCheck (commits 4eda03a / afa8e9d):
    - checks: list of per-subsystem health results
    - overall status degrades to worst check status
    """

    status: str = Field(..., description="服务状态")
    service: str = Field(..., description="服务名称")
    version: str = Field(..., description="服务版本")
    uptime_seconds: Optional[float] = Field(None, description="Process uptime in seconds")
    checks: List[HealthCheck] = Field(default_factory=list, description="Per-subsystem health checks")


class MetricsResponse(BaseModel):
    """指标响应"""

    version: str = Field(..., description="服务版本")
    cli_command: str = Field(..., description="CLI 执行命令")
    requests_total: int = Field(default=0, description="总请求数")
    requests_active: int = Field(default=0, description="活跃请求数")
