"""Compatibility layer for the self-evolution engine.

The primary implementation now lives in src.nanobot.evolve.runtime.
"""

from src.nanobot.evolve.implementation import WorktreeTaskResult
from src.nanobot.evolve.runtime import EvolutionEngine

__all__ = ["EvolutionEngine", "WorktreeTaskResult"]
