# -*- coding: utf-8 -*-

from .parser import (
    SlashCommandParseError,
    CommandSpec,
    OptionDef,
    parse_slash_command,
    usage_for,
    get_known_slash_commands,
    register_slash_command_specs,
    register_slash_spec_loader,
)
from .handler import (
    SlashCommandHandler,
    SLASH_COMMANDS,
    slugify_project,
    register_slash_command_handler,
    register_slash_command_extension,
    register_slash_extension_loader,
)

# Import plan module to trigger extension registration
from . import plan as _plan  # noqa: F401

__all__ = [
    "SlashCommandParseError",
    "CommandSpec",
    "OptionDef",
    "parse_slash_command",
    "usage_for",
    "get_known_slash_commands",
    "register_slash_command_specs",
    "register_slash_spec_loader",
    "SlashCommandHandler",
    "SLASH_COMMANDS",
    "slugify_project",
    "register_slash_command_handler",
    "register_slash_command_extension",
    "register_slash_extension_loader",
]
