"""
Module: terminal_multiselect.py

Description:
    Provides a dependency-free, installer-style terminal multiselect control.
    Arrow keys move the active row, Space toggles a checkbox, Enter confirms,
    and optional all/none shortcuts make longer lists practical. Terminal
    state is always restored, including cancellation and errors.

Dependencies:
    - Python standard library only.
"""

from __future__ import annotations

import contextlib
import os
import select
import sys
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import TextIO


KeyReader = Callable[[], str]


@dataclass(frozen=True)
class MultiselectOption:
    """Describe one stable checkbox option.

    Attributes:
        value: Machine-facing value returned for a selected row.
        label: Concise operator-facing option label.
        description: Optional explanation rendered after the label.
    """

    value: str
    label: str
    description: str = ""


def _read_posix_key(file_descriptor: int) -> str:
    """Decode one raw POSIX terminal key into a selector action.

    Args:
        file_descriptor: Raw terminal input descriptor.

    Returns:
        One of ``up``, ``down``, ``toggle``, ``confirm``, ``all``, ``none``,
        ``cancel``, or ``ignore``.
    """

    first = os.read(file_descriptor, 1)
    if first in {b"\r", b"\n"}:
        return "confirm"
    if first == b" ":
        return "toggle"
    if first in {b"a", b"A"}:
        return "all"
    if first in {b"n", b"N"}:
        return "none"
    if first in {b"q", b"Q", b"\x03"}:
        return "cancel"
    if first != b"\x1b":
        return "ignore"
    if not select.select([file_descriptor], [], [], 0.05)[0]:
        return "cancel"
    second = os.read(file_descriptor, 1)
    if second != b"[" or not select.select(
        [file_descriptor], [], [], 0.05
    )[0]:
        return "cancel"
    return {b"A": "up", b"B": "down"}.get(
        os.read(file_descriptor, 1),
        "ignore",
    )


def _read_windows_key() -> str:
    """Decode one Windows console key into a selector action.

    Returns:
        One normalized selector action.
    """

    import msvcrt

    first = msvcrt.getwch()
    if first in {"\r", "\n"}:
        return "confirm"
    if first == " ":
        return "toggle"
    if first.lower() == "a":
        return "all"
    if first.lower() == "n":
        return "none"
    if first.lower() == "q" or first == "\x03":
        return "cancel"
    if first in {"\x00", "\xe0"}:
        return {"H": "up", "P": "down"}.get(msvcrt.getwch(), "ignore")
    if first == "\x1b":
        return "cancel"
    return "ignore"


@contextlib.contextmanager
def _terminal_key_reader() -> Iterator[KeyReader]:
    """Yield a platform key reader while preserving terminal state.

    Yields:
        Callable returning normalized selector actions.

    Raises:
        OSError: If the active input stream cannot enter raw terminal mode.
    """

    if os.name == "nt":
        yield _read_windows_key
        return

    import termios
    import tty

    file_descriptor = sys.stdin.fileno()
    prior = termios.tcgetattr(file_descriptor)
    try:
        tty.setraw(file_descriptor)
        yield lambda: _read_posix_key(file_descriptor)
    finally:
        termios.tcsetattr(file_descriptor, termios.TCSADRAIN, prior)


def _option_text(option: MultiselectOption) -> str:
    """Build one human-readable option line body.

    Args:
        option: Checkbox option to describe.

    Returns:
        Label with its optional description.
    """

    if not option.description:
        return option.label
    return f"{option.label} - {option.description}"


def _render_lines(
    title: str,
    explanation: str,
    options: Sequence[MultiselectOption],
    selected: set[str],
    cursor: int,
    status: str,
) -> list[str]:
    """Render the complete fixed-height selector frame.

    Args:
        title: Question heading.
        explanation: Short description of the selected values' purpose.
        options: Stable checkbox rows.
        selected: Currently selected option values.
        cursor: Zero-based active-row index.
        status: Optional validation or cancellation guidance.

    Returns:
        Terminal lines for one complete selector frame.
    """

    lines = [
        title,
        explanation,
        "Use Up/Down to navigate, Space to toggle, Enter to confirm ",
        "(A = all, N = none, Esc/Ctrl+C = cancel).",
        "",
    ]
    for index, option in enumerate(options):
        pointer = ">" if index == cursor else " "
        marker = "X" if option.value in selected else " "
        lines.append(f"{pointer} [{marker}] {_option_text(option)}")
    lines.extend(("", status))
    return lines


def _paint_frame(
    output: TextIO,
    lines: Sequence[str],
    prior_line_count: int,
) -> None:
    """Paint or redraw one selector frame without scrolling.

    Args:
        output: Terminal-compatible output stream.
        lines: Current fixed-height frame.
        prior_line_count: Number of lines in the previous frame, or zero for
            the initial paint.

    Returns:
        Nothing after flushing the frame.
    """

    if prior_line_count:
        output.write(f"\r\x1b[{prior_line_count - 1}A")
    for index, line in enumerate(lines):
        output.write(f"\r\x1b[2K{line}")
        if index < len(lines) - 1:
            output.write("\n")
    output.flush()


def _validated_defaults(
    options: Sequence[MultiselectOption],
    defaults: Sequence[str],
) -> set[str]:
    """Validate option identity and normalize selected defaults.

    Args:
        options: Available stable options.
        defaults: Initially selected option values.

    Returns:
        Mutable selected-value set.

    Raises:
        ValueError: If options are duplicated or a default is unknown.
    """

    values = [option.value for option in options]
    if len(values) != len(set(values)):
        raise ValueError("Multiselect option values must be unique.")
    unknown = set(defaults) - set(values)
    if unknown:
        raise ValueError(
            "Multiselect defaults contain unknown values: "
            + ", ".join(sorted(unknown))
        )
    return set(defaults)


def _apply_action(
    action: str,
    options: Sequence[MultiselectOption],
    selected: set[str],
    cursor: int,
    require_selection: bool,
) -> tuple[int, str, str]:
    """Apply one normalized key action to selector state.

    Args:
        action: Normalized key-reader action.
        options: Stable checkbox rows.
        selected: Mutable selected-value set.
        cursor: Current active-row index.
        require_selection: Whether empty confirmation is forbidden.

    Returns:
        Updated cursor, status message, and ``continue``, ``confirm``, or
        ``cancel`` outcome.
    """

    if action == "up":
        return (cursor - 1) % len(options), "", "continue"
    if action == "down":
        return (cursor + 1) % len(options), "", "continue"
    if action == "toggle":
        selected.symmetric_difference_update({options[cursor].value})
    elif action == "all":
        selected.update(option.value for option in options)
    elif action == "none":
        selected.clear()
    elif action == "cancel":
        return cursor, "", "cancel"
    elif action == "confirm":
        if require_selection and not selected:
            return (
                cursor,
                "Select at least one option before confirming.",
                "continue",
            )
        return cursor, "", "confirm"
    return cursor, "", "continue"


def select_many(
    title: str,
    explanation: str,
    options: Sequence[MultiselectOption],
    defaults: Sequence[str] = (),
    *,
    require_selection: bool = False,
    key_reader: KeyReader | None = None,
    output: TextIO | None = None,
    interactive: bool | None = None,
) -> tuple[str, ...]:
    """Run an installer-style checkbox selector.

    Args:
        title: Question heading.
        explanation: Short explanation rendered above the choices.
        options: Stable options in display and return order.
        defaults: Initially selected values.
        require_selection: Prevent Enter while every option is clear.
        key_reader: Optional injected action reader used by automated tests.
        output: Optional display stream; defaults to standard output.
        interactive: Optional TTY override used by automated tests.

    Returns:
        Selected values in original option order. A non-interactive stream
        safely retains the supplied defaults.

    Raises:
        KeyboardInterrupt: If Esc, Q, or Ctrl+C cancels the selector.
        ValueError: If option/default identity is inconsistent.
    """

    if not options:
        return ()
    selected = _validated_defaults(options, defaults)
    display = output or sys.stdout
    if interactive is None:
        interactive = key_reader is not None or (
            sys.stdin.isatty() and display.isatty()
        )
    if not interactive:
        print(
            f"[INFO] {title}: non-interactive terminal; keeping defaults.",
            file=display,
        )
        return tuple(
            option.value for option in options if option.value in selected
        )

    cursor = 0
    status = ""
    prior_line_count = 0
    context = (
        contextlib.nullcontext(key_reader)
        if key_reader is not None
        else _terminal_key_reader()
    )
    with context as read_key:
        while True:
            lines = _render_lines(
                title,
                explanation,
                options,
                selected,
                cursor,
                status,
            )
            _paint_frame(display, lines, prior_line_count)
            prior_line_count = len(lines)
            cursor, status, outcome = _apply_action(
                read_key(),
                options,
                selected,
                cursor,
                require_selection,
            )
            if outcome == "cancel":
                display.write("\r\n")
                raise KeyboardInterrupt
            if outcome == "confirm":
                display.write("\r\n")
                break
    return tuple(option.value for option in options if option.value in selected)


__all__ = ["MultiselectOption", "select_many"]
