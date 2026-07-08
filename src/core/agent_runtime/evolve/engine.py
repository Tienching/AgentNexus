"""Compatibility layer for the self-evolution engine.

The primary implementation now lives in src.core.agent_runtime.evolve.runtime.
"""

from src.core.agent_runtime.evolve.implementation import WorktreeTaskResult
from src.core.agent_runtime.evolve.runtime import EvolutionEngine

__all__ = ["EvolutionEngine", "WorktreeTaskResult"]
