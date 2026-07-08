"""Self-evolution system for agent-nexus.

Provides autonomous self-assessment, planning, and implementation
capabilities using CodeBuddy as the execution agent.
"""

from src.core.agent_runtime.evolve.engine import EvolutionEngine, WorktreeTaskResult
from src.core.agent_runtime.evolve.memory import MemoryManager
from src.core.agent_runtime.evolve.identity import IdentityManager

__all__ = ["EvolutionEngine", "WorktreeTaskResult", "MemoryManager", "IdentityManager"]
