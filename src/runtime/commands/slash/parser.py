# -*- coding: utf-8 -*-
"""Unified slash command parser.

Grammar (strict):
  /<cmd> <subcmd> [options...] [-- <free-text...>]

Rules:
- Sub-command is required for every cmd.
- Free text (if any) MUST appear after `--`.
- Tokens are split using POSIX `shlex` rules (quotes/escapes supported).
- All options MUST have both short (-x) and long (--xxxx) forms defined in schema.

This module only parses + validates tokens and returns a structured command.
Business execution is handled elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import shlex
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class OptionDef:
    short: str  # e.g. 'n'
    long: str  # e.g. 'tail'
    type: str = "string"  # 'string' | 'number' | 'boolean'
    required: bool = False
    default: Any = None

    @property
    def short_flag(self) -> str:
        return f"-{self.short}"

    @property
    def long_flag(self) -> str:
        return f"--{self.long}"

    @property
    def takes_value(self) -> bool:
        return self.type in ("string", "number")


@dataclass(frozen=True)
class CommandSpec:
    cmd: str
    subcmd: str
    options: Tuple[OptionDef, ...] = ()
    allow_free_text: bool = False
    free_text_required: bool = False


@dataclass(frozen=True)
class ParsedSlashCommand:
    cmd: str
    subcmd: str
    options: Dict[str, Any]
    free_text: str
    args: List[str] = field(default_factory=list)


class SlashCommandParseError(ValueError):
    def __init__(self, message: str, usage: str = ""):
        super().__init__(message)
        self.message = message
        self.usage = usage


# -----------------
# Registry / Schema
# -----------------

# NOTE: keep this list in sync with SlashCommandHandler.SLASH_COMMANDS
KNOWN_SLASH_COMMANDS = [
    "/task",
    "/check",
    "/usage",
    "/report",
    "/cancel",
    "/trash",
    "/clear",
    "/help",
    "/chat",
    "/workspace",
    "/config",
    "/switch",
    "/history",
    "/worktree",
    "/exit",
]

# Default subcommand when omitted (None means subcommand is required)
DEFAULT_SUBCMD: Dict[str, Optional[str]] = {
    "task": "create",
    "check": "status",
    "usage": "show",
    "help": "show",
    "clear": "now",
    "report": "daily",
    "trash": "list",
    "cancel": "task",  # will be inferred from -t/-p
    "chat": "history",
    "workspace": "switch",
    "config": "show",
    "switch": "now",
    "history": "list",
    "worktree": "list",
    "exit": "now",
}

# Commands where subcmd can be inferred from options (-t -> task, -p -> project, etc.)
INFER_SUBCMD_FROM_OPTIONS: Dict[str, Dict[str, str]] = {
    "cancel": {"t": "task", "p": "project"},
    "report": {"t": "task", "p": "project", "l": "list"},
    "trash": {"p": "restore", "e": "empty"},
    "chat": {"c": "continue"},
    "config": {"s": "set", "r": "reset", "c": "concurrency"},
    "history": {"s": "jsonl", "f": "fetch", "c": "continue"},
    "worktree": {"s": "create", "a": "create", "l": "list", "g": "gc", "r": "remove"},
}

# Dynamic extension registry (MC-062)
_EXTERNAL_SPECS: List[CommandSpec] = []
_EXTERNAL_DEFAULT_SUBCMD: Dict[str, Optional[str]] = {}
_EXTERNAL_INFER_SUBCMD: Dict[str, Dict[str, str]] = {}
_SPEC_LOADERS: List[Callable[[], None]] = []
_SPEC_LOADERS_RAN: bool = False


def register_slash_command_specs(
    specs: List[CommandSpec],
    *,
    command: Optional[str] = None,
    default_subcmd: Optional[str] = None,
    infer_subcmd_from_options: Optional[Dict[str, str]] = None,
) -> None:
    """Register additional slash command specs at runtime."""
    global _EXTERNAL_SPECS
    for spec in specs or []:
        _EXTERNAL_SPECS.append(spec)
    if command and default_subcmd is not None:
        _EXTERNAL_DEFAULT_SUBCMD[command] = default_subcmd
    if command and infer_subcmd_from_options:
        _EXTERNAL_INFER_SUBCMD[command] = dict(infer_subcmd_from_options)


def register_slash_spec_loader(loader: Callable[[], None]) -> None:
    """Register a lazy loader that can inject slash command specs."""
    _SPEC_LOADERS.append(loader)


def _ensure_spec_loaders_ran() -> None:
    global _SPEC_LOADERS_RAN
    if _SPEC_LOADERS_RAN:
        return
    for loader in list(_SPEC_LOADERS):
        loader()
    _SPEC_LOADERS_RAN = True


def _build_runtime_registry() -> Tuple[List[CommandSpec], Dict[Tuple[str, str], CommandSpec], Dict[str, Optional[str]], Dict[str, Dict[str, str]], List[str]]:
    _ensure_spec_loaders_ran()

    specs = list(SPECS) + list(_EXTERNAL_SPECS)
    spec_by = _spec_index(specs)

    defaults = dict(DEFAULT_SUBCMD)
    defaults.update(_EXTERNAL_DEFAULT_SUBCMD)

    infer_map = {k: dict(v) for k, v in INFER_SUBCMD_FROM_OPTIONS.items()}
    for cmd, mapping in _EXTERNAL_INFER_SUBCMD.items():
        infer_map[cmd] = dict(mapping)

    known_commands = sorted({f"/{s.cmd}" for s in specs})
    return specs, spec_by, defaults, infer_map, known_commands


def get_known_slash_commands() -> List[str]:
    """Return all built-in + dynamically registered slash commands."""
    _, _, _, _, known_commands = _build_runtime_registry()
    return known_commands


def _spec_index(specs: List[CommandSpec]) -> Dict[Tuple[str, str], CommandSpec]:
    return {(s.cmd, s.subcmd): s for s in specs}


def _options_index(spec: CommandSpec) -> Tuple[Dict[str, OptionDef], Dict[str, OptionDef]]:
    by_short: Dict[str, OptionDef] = {}
    by_long: Dict[str, OptionDef] = {}
    for opt in spec.options:
        if not opt.short or not opt.long:
            raise RuntimeError(f"Option must define both short and long: {opt}")
        if opt.short in by_short:
            raise RuntimeError(f"Duplicate short option '-{opt.short}' for {spec.cmd} {spec.subcmd}")
        if opt.long in by_long:
            raise RuntimeError(f"Duplicate long option '--{opt.long}' for {spec.cmd} {spec.subcmd}")
        by_short[opt.short] = opt
        by_long[opt.long] = opt
    return by_short, by_long


SPECS: List[CommandSpec] = [
    # task
    CommandSpec(
        cmd="task",
        subcmd="create",
        options=(
            OptionDef(short="p", long="project", type="string", required=False, default=None),
            OptionDef(short="w", long="workspace", type="string", required=False, default=None),
            OptionDef(short="i", long="inplace", type="boolean", required=False, default=False),
            OptionDef(short="u", long="exec-user", type="string", required=False, default=None),
            OptionDef(short="r", long="provider", type="string", required=False, default=None),
            OptionDef(short="l", long="alias", type="string", required=False, default=None),
            OptionDef(short="m", long="model", type="string", required=False, default=None),
        ),
        allow_free_text=True,
        free_text_required=True,
    ),
    # chat
    CommandSpec(
        cmd="chat",
        subcmd="continue",
        options=(
            OptionDef(short="c", long="continue", type="boolean", required=False, default=True),
            OptionDef(short="t", long="task", type="string", required=True),
            OptionDef(short="m", long="model", type="string", required=False, default=None),
        ),
        allow_free_text=True,
        free_text_required=True,
    ),
    CommandSpec(
        cmd="chat",
        subcmd="history",
        options=(
            OptionDef(short="t", long="task", type="string", required=True),
            OptionDef(short="n", long="tail", type="number", required=False, default=10),
        ),
        allow_free_text=False,
        free_text_required=False,
    ),
    # check/usage/help
    CommandSpec(cmd="check", subcmd="status"),
    CommandSpec(cmd="usage", subcmd="show"),
    CommandSpec(cmd="help", subcmd="show"),
    # report
    CommandSpec(cmd="report", subcmd="daily"),
    CommandSpec(
        cmd="report",
        subcmd="task",
        options=(OptionDef(short="t", long="task", type="string", required=True),),
    ),
    CommandSpec(
        cmd="report",
        subcmd="project",
        options=(OptionDef(short="p", long="project", type="string", required=True),),
    ),
    CommandSpec(
        cmd="report",
        subcmd="list",
        options=(OptionDef(short="l", long="list", type="boolean", required=False, default=True),),
    ),
    # cancel
    CommandSpec(
        cmd="cancel",
        subcmd="task",
        options=(OptionDef(short="t", long="task", type="string", required=True),),
    ),
    CommandSpec(
        cmd="cancel",
        subcmd="project",
        options=(OptionDef(short="p", long="project", type="string", required=True),),
    ),
    # trash
    CommandSpec(
        cmd="trash",
        subcmd="list",
    ),
    CommandSpec(
        cmd="trash",
        subcmd="restore",
        options=(OptionDef(short="p", long="project", type="string", required=True),),
    ),
    CommandSpec(
        cmd="trash",
        subcmd="empty",
        options=(OptionDef(short="e", long="empty", type="boolean", required=False, default=True),),
    ),
    # clear
    CommandSpec(cmd="clear", subcmd="now"),
    # workspace
    CommandSpec(
        cmd="workspace",
        subcmd="switch",
        options=(
            OptionDef(short="w", long="workspace", type="string", required=False),
            OptionDef(short="t", long="task", type="string", required=False),
        ),
    ),
    # config
    CommandSpec(cmd="config", subcmd="show"),
    CommandSpec(
        cmd="config",
        subcmd="set",
        options=(OptionDef(short="s", long="set", type="boolean", required=False, default=True),),
    ),
    CommandSpec(
        cmd="config",
        subcmd="reset",
        options=(OptionDef(short="r", long="reset", type="boolean", required=False, default=True),),
    ),
    CommandSpec(
        cmd="config",
        subcmd="concurrency",
        options=(OptionDef(short="c", long="concurrency", type="boolean", required=False, default=True),),
    ),
    # switch
    CommandSpec(
        cmd="switch",
        subcmd="now",
        options=(
            OptionDef(short="r", long="provider", type="string", required=False),
            OptionDef(short="l", long="alias", type="string", required=False),
            OptionDef(short="m", long="model", type="string", required=False),
            OptionDef(short="u", long="exec-user", type="string", required=False),
            OptionDef(short="a", long="auto", type="boolean", required=False, default=False),
            OptionDef(short="x", long="context-mode", type="string", required=False, default="full"),  # full | windowed
        ),
        allow_free_text=True,
        free_text_required=False,
    ),
    # history
    CommandSpec(
        cmd="history",
        subcmd="list",
        options=(
            OptionDef(short="n", long="num", type="number", required=False, default=10),
            OptionDef(short="r", long="provider", type="string", required=False),
            OptionDef(short="u", long="user", type="string", required=False),
        ),
        allow_free_text=False,
    ),
    CommandSpec(
        cmd="history",
        subcmd="jsonl",
        options=(
            OptionDef(short="s", long="session", type="string", required=False),
            OptionDef(short="u", long="user", type="string", required=False),
        ),
        allow_free_text=False,
    ),
    CommandSpec(
        cmd="history",
        subcmd="fetch",
        options=(
            OptionDef(short="f", long="fetch", type="boolean", required=False, default=False),
            OptionDef(short="s", long="session", type="string", required=True),
            OptionDef(short="u", long="user", type="string", required=False),
        ),
        allow_free_text=False,
    ),
    CommandSpec(
        cmd="history",
        subcmd="continue",
        options=(
            OptionDef(short="c", long="continue", type="boolean", required=False, default=False),
            OptionDef(short="s", long="session", type="string", required=True),
            OptionDef(short="u", long="user", type="string", required=False),
        ),
        allow_free_text=False,
    ),
    # exit
    CommandSpec(cmd="exit", subcmd="now"),
    # worktree
    CommandSpec(
        cmd="worktree",
        subcmd="create",
        options=(
            OptionDef(short="s", long="session", type="boolean", required=False, default=False),
            OptionDef(short="a", long="agent", type="boolean", required=False, default=False),
            OptionDef(short="t", long="task", type="string", required=False),
            OptionDef(short="k", long="key", type="string", required=False),
        ),
        allow_free_text=False,
    ),
    CommandSpec(
        cmd="worktree",
        subcmd="list",
        options=(
            OptionDef(short="l", long="list", type="boolean", required=False, default=True),
            OptionDef(short="a", long="active", type="boolean", required=False, default=False),
            OptionDef(short="g", long="stale", type="boolean", required=False, default=False),
        ),
        allow_free_text=False,
    ),
    CommandSpec(
        cmd="worktree",
        subcmd="resume",
        options=(
            OptionDef(short="s", long="session", type="string", required=False),
            OptionDef(short="a", long="agent", type="string", required=False),
        ),
        allow_free_text=False,
    ),
    CommandSpec(
        cmd="worktree",
        subcmd="gc",
        options=(
            OptionDef(short="g", long="gc", type="boolean", required=False, default=True),
            OptionDef(short="d", long="dry-run", type="boolean", required=False, default=False),
            OptionDef(short="m", long="max-age", type="number", required=False, default=24),
        ),
        allow_free_text=False,
    ),
    CommandSpec(
        cmd="worktree",
        subcmd="remove",
        options=(
            OptionDef(short="r", long="remove", type="boolean", required=False, default=True),
            OptionDef(short="i", long="id", type="string", required=True),
        ),
        allow_free_text=False,
    ),
]

SPEC_BY_CMD_SUBCMD = _spec_index(SPECS)


def usage_for(cmd: str, subcmd: Optional[str] = None) -> str:
    """Generate a concise usage string."""
    specs, spec_by, _, _, _ = _build_runtime_registry()

    if subcmd is None:
        subs = sorted({s.subcmd for s in specs if s.cmd == cmd})
        if not subs:
            return ""
        joined = " | ".join(subs)
        return f"/{cmd} <{joined}> [options...] -- <text>"

    spec = spec_by.get((cmd, subcmd))
    if not spec:
        return ""

    opt_parts: List[str] = []
    for o in spec.options:
        if o.takes_value:
            opt_parts.append(f"[{o.short_flag}|{o.long_flag} <value>]")
        else:
            opt_parts.append(f"[{o.short_flag}|{o.long_flag}]")

    opt_str = " ".join(opt_parts)
    if spec.allow_free_text:
        text = "-- <text...>" if spec.free_text_required else "[-- <text...>]"
        return f"/{cmd} {subcmd} {opt_str} {text}".strip()

    return f"/{cmd} {subcmd} {opt_str}".strip()


# ---------------
# Parser / Validate
# ---------------


def _split_before_after_double_dash(tokens: List[str]) -> Tuple[List[str], List[str]]:
    if "--" not in tokens:
        return tokens, []
    idx = tokens.index("--")
    return tokens[:idx], tokens[idx + 1 :]


def _coerce_value(opt: OptionDef, raw: str) -> Any:
    if opt.type == "string":
        return raw
    if opt.type == "number":
        try:
            return int(raw)
        except ValueError as e:
            raise SlashCommandParseError(
                f"参数 {opt.long_flag} 需要数字，但收到: {raw}",
                usage="",
            ) from e
    if opt.type == "boolean":
        # for future
        return bool(raw)
    return raw


def _infer_subcmd_from_tokens(cmd: str, tokens: List[str], infer_registry: Optional[Dict[str, Dict[str, str]]] = None) -> Optional[str]:
    """Infer subcmd from option flags in tokens (e.g., -t -> task, -p -> project)."""
    registry = infer_registry or INFER_SUBCMD_FROM_OPTIONS
    infer_map = registry.get(cmd)
    if not infer_map:
        return None
    
    for tok in tokens:
        if tok.startswith("-") and not tok.startswith("--") and len(tok) == 2:
            short = tok[1]
            if short in infer_map:
                return infer_map[short]
        elif tok.startswith("--"):
            long_name = tok[2:].split("=")[0]  # handle --key=value
            # Map long names to short for lookup
            long_to_short = {
                "task": "t", "project": "p", "list": "l",
                "continue": "c", "empty": "e",
                "set": "s", "reset": "r",
                "session": "s", "fetch": "f",
            }
            short = long_to_short.get(long_name)
            if short and short in infer_map:
                return infer_map[short]
    return None


def parse_slash_command(text: str) -> ParsedSlashCommand:
    """Parse and validate a slash command input."""
    try:
        tokens = shlex.split(text, posix=True)
    except ValueError as e:
        raise SlashCommandParseError(f"命令解析失败: {e}") from e

    if not tokens:
        raise SlashCommandParseError("空命令")

    cmd_token = tokens[0].lower()
    if not cmd_token.startswith("/"):
        raise SlashCommandParseError("不是 slash command")

    cmd = cmd_token[1:]
    _, spec_by_cmd_subcmd, default_subcmds, infer_subcmd_map, known_slash_commands = _build_runtime_registry()

    if ("/" + cmd) not in known_slash_commands:
        raise SlashCommandParseError(f"未知命令: /{cmd}")

    # All tokens after command are options/free-text (no explicit subcommand)
    rest_tokens = tokens[1:]

    # Infer subcmd from options, or use default
    inferred = _infer_subcmd_from_tokens(cmd, rest_tokens, infer_registry=infer_subcmd_map)
    if inferred:
        subcmd = inferred
    else:
        default_sub = default_subcmds.get(cmd)
        if default_sub:
            subcmd = default_sub
        else:
            raise SlashCommandParseError(
                f"命令 /{cmd} 缺少必要参数",
                usage=usage_for(cmd),
            )

    spec = spec_by_cmd_subcmd.get((cmd, subcmd))
    if not spec:
        raise SlashCommandParseError(
            f"命令 /{cmd} 内部错误: {subcmd}",
            usage=usage_for(cmd),
        )

    before_dd, after_dd = _split_before_after_double_dash(rest_tokens)

    by_short, by_long = _options_index(spec)
    options: Dict[str, Any] = {}
    args: List[str] = []

    i = 0
    while i < len(before_dd):
        tok = before_dd[i]

        if tok.startswith("--"):
            # long option
            if tok == "--":
                raise SlashCommandParseError("内部错误：重复的 --")

            if "=" in tok:
                name, raw_val = tok[2:].split("=", 1)
                opt = by_long.get(name)
                if not opt:
                    raise SlashCommandParseError(
                        f"未知参数: --{name}",
                        usage=usage_for(cmd, subcmd),
                    )
                if not opt.takes_value:
                    raise SlashCommandParseError(
                        f"参数 {opt.long_flag} 不接受值",
                        usage=usage_for(cmd, subcmd),
                    )
                val = _coerce_value(opt, raw_val)
                i += 1
            else:
                name = tok[2:]
                opt = by_long.get(name)
                if not opt:
                    raise SlashCommandParseError(
                        f"未知参数: --{name}",
                        usage=usage_for(cmd, subcmd),
                    )
                if opt.takes_value:
                    if i + 1 >= len(before_dd):
                        raise SlashCommandParseError(
                            f"参数 {opt.long_flag} 缺少值",
                            usage=usage_for(cmd, subcmd),
                        )
                    raw_val = before_dd[i + 1]
                    val = _coerce_value(opt, raw_val)
                    i += 2
                else:
                    val = True
                    i += 1

            if opt.long in options:
                raise SlashCommandParseError(
                    f"参数重复: {opt.long_flag}",
                    usage=usage_for(cmd, subcmd),
                )
            options[opt.long] = val

        elif tok.startswith("-") and len(tok) == 2:
            # short option
            short = tok[1:]
            opt = by_short.get(short)
            if not opt:
                # Treat as positional arg if not a known flag
                args.append(tok)
                i += 1
                continue

            if opt.takes_value:
                if i + 1 >= len(before_dd):
                    raise SlashCommandParseError(
                        f"参数 {opt.short_flag}/{opt.long_flag} 缺少值",
                        usage=usage_for(cmd, subcmd),
                    )
                raw_val = before_dd[i + 1]
                val = _coerce_value(opt, raw_val)
                i += 2
            else:
                val = True
                i += 1

            if opt.long in options:
                raise SlashCommandParseError(
                    f"参数重复: {opt.long_flag}",
                    usage=usage_for(cmd, subcmd),
                )
            options[opt.long] = val

        else:
            # Positional argument
            args.append(tok)
            i += 1


    # defaults & required
    for opt in spec.options:
        if opt.long not in options:
            if opt.required:
                raise SlashCommandParseError(
                    f"缺少必需参数: {opt.short_flag}/{opt.long_flag}",
                    usage=usage_for(cmd, subcmd),
                )
            if opt.default is not None:
                options[opt.long] = opt.default

    free_text = " ".join(after_dd).strip() if after_dd else ""
    if after_dd and not spec.allow_free_text:
        raise SlashCommandParseError(
            "该命令不接受自由文本（请删除 -- 及其后内容）",
            usage=usage_for(cmd, subcmd),
        )
    if spec.free_text_required and not free_text:
        raise SlashCommandParseError(
            "缺少正文（请在 -- 之后提供文本）",
            usage=usage_for(cmd, subcmd),
        )

    return ParsedSlashCommand(cmd=cmd, subcmd=subcmd, options=options, free_text=free_text, args=args)
