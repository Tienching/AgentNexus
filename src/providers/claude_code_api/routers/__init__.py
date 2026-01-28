"""路由模块 (re-export)"""

from src.server.routers import chat_router, health_router

__all__ = [
    "chat_router",
    "health_router",
]
