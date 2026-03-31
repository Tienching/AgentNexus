"""Self-evolution system for agent-nexus.

Provides autonomous self-assessment, planning, and implementation
capabilities using CodeBuddy as the execution agent.
"""

from src.nanobot.evolve.engine import EvolutionEngine
from src.nanobot.evolve.memory import MemoryManager
from src.nanobot.evolve.identity import IdentityManager

__all__ = ["EvolutionEngine", "MemoryManager", "IdentityManager"]
