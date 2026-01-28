# -*- coding: utf-8 -*-
"""CCR Executor re-export

This module re-exports the CCRExecutor from server layer for backward compatibility.
New code should prefer importing from src.runtime.executors for runtime-layer usage.
"""

from src.server.services.ccr_executor import CCRExecutor  # noqa: F401

# Also export the runtime executor for migration
from src.runtime.executors import CCRExecutor as RuntimeCCRExecutor  # noqa: F401
from src.runtime.executors import RequestContext  # noqa: F401

__all__ = ["CCRExecutor", "RuntimeCCRExecutor", "RequestContext"]
