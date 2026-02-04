# -*- coding: utf-8 -*-
"""Provider registry for HTTP layer.

This module handles HTTP-specific provider resolution (query/body/session lookup).
"""

from .registry import ProviderRegistry, get_provider_registry

__all__ = [
    "ProviderRegistry",
    "get_provider_registry",
]
