"""
Module: terminal_status.py

Description:
    Provides semantic ANSI coloring for Python-backed operator actions. Output
    is colored only on interactive terminals; redirected logs, tests,
    ``TERM=dumb``, and a nonempty ``NO_COLOR`` override remain plain.

Dependencies:
    - Python standard library.
"""

from __future__ import annotations

import os
import sys
from typing import TextIO


# Shared ANSI SGR prefixes mirror the Bash operator-menu palette.
STATUS_COLOR_CODES = {
    "ok": "\033[32m",
    "warning": "\033[33m",
    "error": "\033[31m",
    "info": "\033[36m",
}


def colorize_status_text(text: str, level: str, stream: TextIO) -> str:
    """Apply one semantic color when output targets an interactive terminal.

    Args:
        text: Complete operator-facing status line.
        level: Semantic level: ``ok``, ``warning``, ``error``, or ``info``.
        stream: Output stream whose terminal capability controls coloring.

    Returns:
        ANSI-wrapped text for an eligible terminal, otherwise unchanged text.

    Note:
        Redirected output, ``TERM=dumb``, and a nonempty ``NO_COLOR`` value
        deliberately remain plain for logs, tests, and automation.
    """

    color = STATUS_COLOR_CODES.get(level)
    colors_disabled = bool(os.environ.get("NO_COLOR"))
    terminal_is_dumb = os.environ.get("TERM", "dumb") == "dumb"
    if (
        color is None
        or colors_disabled
        or terminal_is_dumb
        or not stream.isatty()
    ):
        return text
    return f"{color}{text}\033[0m"


def print_status(
    text: str,
    level: str,
    *,
    stream: TextIO | None = None,
) -> None:
    """Print one semantic operator status with terminal-aware coloring.

    Args:
        text: Complete operator-facing status line.
        level: Semantic level: ``ok``, ``warning``, ``error``, or ``info``.
        stream: Optional output stream; defaults to the current ``sys.stdout``.

    Returns:
        Nothing.

    Side Effects:
        Writes exactly one newline-terminated status line to the selected
        stream.
    """

    target = stream if stream is not None else sys.stdout
    print(colorize_status_text(text, level, target), file=target)
