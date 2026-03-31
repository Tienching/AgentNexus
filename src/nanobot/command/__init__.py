"""Slash command routing and built-in handlers."""

from src.nanobot.command.builtin import register_builtin_commands
from src.nanobot.command.router import CommandContext, CommandRouter

__all__ = ["CommandContext", "CommandRouter", "register_builtin_commands"]
