"""Identity management for the self-evolution system.

Loads and manages project identity files (IDENTITY.md, PERSONALITY.md)
that define who the agent is and how it behaves.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from src.nanobot.evolve.models import EvolutionConfig


class IdentityManager:
    """Manages project identity and personality files."""

    def __init__(self, config: EvolutionConfig):
        self.config = config
        self._base = Path(config.working_dir).resolve()

    @property
    def identity_path(self) -> Path:
        return self._base / self.config.identity_file

    @property
    def personality_path(self) -> Path:
        return self._base / self.config.personality_file

    def load_identity(self) -> str:
        """Load IDENTITY.md content."""
        if self.identity_path.exists():
            try:
                return self.identity_path.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning("Failed to read IDENTITY.md: {}", e)
        return ""

    def load_personality(self) -> str:
        """Load PERSONALITY.md content."""
        if self.personality_path.exists():
            try:
                return self.personality_path.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning("Failed to read PERSONALITY.md: {}", e)
        return ""

    def build_context(self, active_learnings: str = "", social_learnings: str = "") -> str:
        """Build the full identity context string for prompts.

        Returns a structured context block with identity, personality,
        self-wisdom, and social wisdom sections.
        """
        identity = self.load_identity()
        personality = self.load_personality()

        sections = []

        sections.append("=== WHO YOU ARE ===\n")
        sections.append(identity if identity else "No identity file found. You are agent-nexus, a self-evolving AI orchestration system.")

        sections.append("\n\n=== YOUR VOICE ===\n")
        sections.append(personality if personality else "Be clear, precise, and methodical. Focus on measurable improvements.")

        sections.append("\n\n=== SELF-WISDOM ===\n")
        sections.append(active_learnings if active_learnings else "No learnings yet. This is your first evolution session.")

        sections.append("\n\n=== SOCIAL WISDOM ===\n")
        sections.append(social_learnings if social_learnings else "No social learnings yet.")

        return "".join(sections)

    def get_protected_files(self) -> list[str]:
        """Get the list of files that must not be modified during evolution."""
        return list(self.config.protected_files)

    def validate_changes(self, changed_files: list[str]) -> tuple[bool, list[str]]:
        """Check if any changed files are protected.

        Returns:
            (is_valid, list_of_violations)
        """
        protected = self.get_protected_files()
        violations = [f for f in changed_files if any(f.endswith(p) or f == p for p in protected)]
        return len(violations) == 0, violations
