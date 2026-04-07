"""适配器基类定义"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, Optional, AsyncGenerator
import json


class ProtocolType(str, Enum):
    """协议类型"""
    AGUI = "agui"


class AdapterState:
    """适配器状态管理"""
    
    def __init__(self, thread_id: str, run_id: str):
        self.thread_id = thread_id
        self.run_id = run_id
        self.current_message_id: Optional[str] = None
        self.message_started = False
        self.tool_input_buffer: Dict[int, tuple] = {}  # index -> (tool_name, tool_id, params)
        self.active_tool_calls: Dict[str, str] = {}  # tool_id -> tool_name
        self.run_started = False
        self.run_finished = False
        self.has_error = False  # 标记是否发生错误


class BaseAdapter(ABC):
    """协议适配器基类"""
    
    def __init__(self):
        self.state: Optional[AdapterState] = None
    
    def init_state(self, thread_id: str, run_id: str) -> None:
        """初始化适配器状态"""
        self.state = AdapterState(thread_id, run_id)
    
    @property
    @abstractmethod
    def protocol_type(self) -> ProtocolType:
        """返回协议类型"""
        pass
    
    @abstractmethod
    def convert(self, claude_event: Dict[str, Any]) -> Optional[str]:
        """
        转换Claude事件为目标协议格式
        
        Args:
            claude_event: Claude stream-json 事件
            
        Returns:
            目标协议格式的SSE字符串，如果不需要输出则返回None
        """
        pass
    
    @abstractmethod
    def format_sse(self, data: Any) -> str:
        """
        格式化为SSE格式
        
        Args:
            data: 要发送的数据
            
        Returns:
            SSE格式的字符串
        """
        pass
    
    @abstractmethod
    def create_start_event(self) -> Optional[str]:
        """
        创建流开始事件
        
        Returns:
            SSE格式的开始事件
        """
        pass
    
    @abstractmethod
    def create_end_event(self, is_error: bool = False, error_msg: str = "") -> str:
        """
        创建流结束事件
        
        Args:
            is_error: 是否为错误结束
            error_msg: 错误消息
            
        Returns:
            SSE格式的结束事件
        """
        pass
    
    @abstractmethod
    def create_error_event(self, error_msg: str) -> str:
        """
        创建错误事件
        
        Args:
            error_msg: 错误消息
            
        Returns:
            SSE格式的错误事件
        """
        pass
    
    def parse_json_line(self, line: str) -> Optional[Dict[str, Any]]:
        """
        解析JSON行
        
        Args:
            line: JSON字符串
            
        Returns:
            解析后的字典，解析失败返回None
        """
        try:
            return json.loads(line.strip())
        except json.JSONDecodeError:
            return None
    
    async def process_stream(
        self, 
        claude_stream: AsyncGenerator[str, None]
    ) -> AsyncGenerator[str, None]:
        """
        处理Claude流并转换为目标协议格式
        
        Args:
            claude_stream: Claude stream-json 流
            
        Yields:
            目标协议格式的SSE事件
        """
        # 发送开始事件
        start_event = self.create_start_event()
        if start_event:
            yield start_event
        
        async for line in claude_stream:
            if not line.strip():
                continue
            
            event_data = self.parse_json_line(line)
            if event_data:
                converted = self.convert(event_data)
                if converted:
                    yield converted
        
        # 发送结束事件
        end_event = self.create_end_event()
        if end_event:
            yield end_event
