"""Tests for the repository-wide temporary secret viewing contract."""

from __future__ import annotations

import stat
import sys
import tempfile
import unittest
from collections.abc import Mapping, Sequence
from pathlib import Path
from unittest.mock import patch
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIRECTORY = REPOSITORY_ROOT / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

from temporary_secret_viewer import (  # noqa: E402
    SecretViewPresentation,
    consume_private_source_file,
    offer_temporary_secret_view,
    view_secret_temporarily,
)


class TemporarySecretViewerTests(unittest.TestCase):
    """Exercise shared handoff, opt-in, editor, and cleanup behavior."""

    def setUp(self) -> None:
        """Create a disposable parent for each viewer invocation."""

        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.runtime_root = Path(self.temporary.name)
        self.presentation = SecretViewPresentation(
            heading="Test recovery",
            notices=(
                "Copy the values yourself.",
                "The file is deleted immediately after editor close.",
            ),
            prompt="View now? [y/N]: ",
            skipped="Skipped without retaining a file.",
            file_name="recovery.env",
        )

    def test_private_handoff_is_consumed_and_deleted(self) -> None:
        """Read exact content only from a private regular file and unlink it."""

        source = self.runtime_root / "handoff"
        source.write_text("secret=value\n", encoding="utf-8")
        source.chmod(0o600)

        self.assertEqual(consume_private_source_file(source), "secret=value\n")
        self.assertFalse(source.exists())

    def test_view_is_read_only_and_deleted_after_editor_close(self) -> None:
        """Keep content available only while the selected editor is open."""

        observed_path: Path | None = None

        def inspect_editor(
            command: Sequence[str],
            environment: Mapping[str, str],
        ) -> int:
            nonlocal observed_path
            observed_path = Path(command[-1])
            self.assertEqual(observed_path.name, "recovery.env")
            self.assertEqual(
                observed_path.read_text(encoding="utf-8"),
                "first=secret\nsecond=value\n",
            )
            self.assertEqual(stat.S_IMODE(observed_path.stat().st_mode) & 0o222, 0)
            self.assertIn("noswapfile", environment["EXINIT"])
            return 0

        view_secret_temporarily(
            "first=secret\nsecond=value\n",
            "/usr/bin/nano",
            presentation=self.presentation,
            runtime_root=self.runtime_root,
            launcher=inspect_editor,
            output=lambda message: None,
        )

        self.assertIsNotNone(observed_path)
        self.assertFalse(observed_path.exists())  # type: ignore[union-attr]
        self.assertEqual(list(self.runtime_root.iterdir()), [])

    def test_offer_warns_before_opt_in_and_decline_creates_nothing(self) -> None:
        """Tell the operator to copy values and about deletion before asking."""

        messages: list[str] = []
        prompts: list[str] = []

        def decline(prompt: str) -> str:
            prompts.append(prompt)
            return ""

        offer_temporary_secret_view(
            "declined=value",
            presentation=self.presentation,
            input_reader=decline,
            output=messages.append,
            runtime_root=self.runtime_root,
        )

        rendered_before_prompt = "\n".join(messages[:-1])
        self.assertIn("Copy the values yourself", rendered_before_prompt)
        self.assertIn("deleted immediately", rendered_before_prompt)
        self.assertEqual(prompts, ["View now? [y/N]: "])
        self.assertIn("without retaining", messages[-1])
        self.assertEqual(list(self.runtime_root.iterdir()), [])

    def test_offer_supports_configured_visual_editor_without_a_shell(self) -> None:
        """Honor a custom editor command while passing arguments directly."""

        answers = iter(("y", "4"))
        launched: list[tuple[str, ...]] = []

        def record_editor(
            command: Sequence[str],
            environment: Mapping[str, str],
        ) -> int:
            del environment
            launched.append(tuple(command))
            return 0

        with patch.dict("os.environ", {"VISUAL": "code --wait", "EDITOR": ""}):
            offer_temporary_secret_view(
                "custom-editor=value",
                presentation=self.presentation,
                input_reader=lambda prompt: next(answers),
                output=lambda message: None,
                locator=lambda name: f"/usr/bin/{name}",
                runtime_root=self.runtime_root,
                launcher=record_editor,
            )

        self.assertEqual(launched[0][0:2], ("/usr/bin/code", "--wait"))
        self.assertEqual(Path(launched[0][-1]).name, "recovery.env")
        self.assertEqual(list(self.runtime_root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
