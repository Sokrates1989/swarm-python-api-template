"""
Module: test_terminal_multiselect.py

Description:
    Exercises the dependency-free installer-style checkbox state machine
    without requiring a real terminal or changing process terminal settings.

Dependencies:
    - Python standard library.
    - scripts/terminal_multiselect.py.
"""

from __future__ import annotations

import io
import sys
import unittest
from collections.abc import Callable
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIRECTORY = REPOSITORY_ROOT / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

from terminal_multiselect import MultiselectOption, select_many  # noqa: E402


class TerminalMultiselectTests(unittest.TestCase):
    """Verify keyboard navigation, selection, and safe fallbacks."""

    def setUp(self) -> None:
        """Create stable options used by every selector test.

        Returns:
            Nothing.
        """

        self.options = (
            MultiselectOption("user", "user", "Standard user"),
            MultiselectOption("admin", "admin", "Administrator"),
            MultiselectOption("manager", "manager", "Manager"),
        )

    @staticmethod
    def _reader(*actions: str) -> Callable[[], str]:
        """Create a deterministic key-reader callback.

        Args:
            actions: Normalized selector actions returned in order.

        Returns:
            Zero-argument callback compatible with ``select_many``.
        """

        iterator = iter(actions)
        return lambda: next(iterator)

    def test_arrow_navigation_space_toggle_and_enter_confirm(self) -> None:
        """Navigate rows and return selected values in option order.

        Returns:
            Nothing.
        """

        output = io.StringIO()
        selected = select_many(
            "Roles",
            "Choose roles.",
            self.options,
            ("manager",),
            key_reader=self._reader(
                "down",
                "toggle",
                "down",
                "toggle",
                "confirm",
            ),
            output=output,
            interactive=True,
        )

        self.assertEqual(selected, ("admin",))
        self.assertIn("Space to toggle", output.getvalue())
        self.assertIn("[X]", output.getvalue())

    def test_required_selection_rejects_empty_confirmation(self) -> None:
        """Keep the selector open until a required option is checked.

        Returns:
            Nothing.
        """

        output = io.StringIO()
        selected = select_many(
            "User roles",
            "Choose at least one role.",
            self.options,
            require_selection=True,
            key_reader=self._reader("confirm", "toggle", "confirm"),
            output=output,
            interactive=True,
        )

        self.assertEqual(selected, ("user",))
        self.assertIn("Select at least one option", output.getvalue())

    def test_all_none_shortcuts_and_noninteractive_defaults(self) -> None:
        """Support bulk shortcuts and retain defaults without a TTY.

        Returns:
            Nothing.
        """

        selected = select_many(
            "Roles",
            "Choose roles.",
            self.options,
            ("user",),
            key_reader=self._reader("all", "none", "all", "confirm"),
            output=io.StringIO(),
            interactive=True,
        )
        fallback = select_many(
            "Roles",
            "Choose roles.",
            self.options,
            ("manager",),
            output=io.StringIO(),
            interactive=False,
        )

        self.assertEqual(selected, ("user", "admin", "manager"))
        self.assertEqual(fallback, ("manager",))

    def test_escape_or_control_c_cancels_selection(self) -> None:
        """Surface standard terminal cancellation and restore the caller.

        Returns:
            Nothing.
        """

        with self.assertRaises(KeyboardInterrupt):
            select_many(
                "Roles",
                "Choose roles.",
                self.options,
                ("user",),
                key_reader=self._reader("cancel"),
                output=io.StringIO(),
                interactive=True,
            )


if __name__ == "__main__":
    unittest.main()
