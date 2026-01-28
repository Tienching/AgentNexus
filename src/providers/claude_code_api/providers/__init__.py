# -*- coding: utf-8 -*-
"""Provider core (registry + built-in providers).

This layer centralizes provider selection (claude/gemini/...) and provides a
stable extension point for adding a third provider later.

Note: For backward compatibility, unknown provider names still map to the
Claude backend, while the original provider string can still be used for
archiving/session meta.
"""

from .registry import ProviderRegistry, get_provider_registry

__all__ = [
    "ProviderRegistry",
    "get_provider_registry",
]
