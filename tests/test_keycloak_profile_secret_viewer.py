"""
Module: test_keycloak_profile_secret_viewer.py

Description:
    Verifies opt-in Keycloak secret viewing, editor selection, read-only file
    handling, and cleanup on both normal close and interruption.

Dependencies:
    - Python standard library.
    - Shared Keycloak secret-viewer module.
"""

from __future__ import annotations

import stat
import sys
import tempfile
import unittest
from collections.abc import Mapping, Sequence
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIRECTORY = REPOSITORY_ROOT / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

from keycloak_profile_secret_viewer import (  # noqa: E402
    offer_temporary_secret_view,
    view_secret_temporarily,
)


class KeycloakProfileSecretViewerTests(unittest.TestCase):
    """Exercise the one-run recovery-view lifecycle without real editors."""

    def setUp(self) -> None:
        """Create a disposable parent directory for private viewer folders.

        Returns:
            Nothing.
        """

        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.runtime_root = Path(self.temporary.name)

    def test_view_is_read_only_and_deleted_after_editor_close(self) -> None:
        """Expose the exact value only while the injected editor is open.

        Returns:
            Nothing.
        """

        secret = "exact-keycloak-recovery-value"
        observed_paths: list[Path] = []

        def inspect_editor(
            command: Sequence[str],
            environment: Mapping[str, str],
        ) -> int:
            """Inspect the private file while simulating an open editor.

            Args:
                command: Generated read-only editor command.
                environment: Backup-resistant child environment.

            Returns:
                Successful editor exit status.
            """

            secret_path = Path(command[-1])
            observed_paths.append(secret_path)
            self.assertEqual(secret_path.name, "temp_keycloak_secret.txt")
            self.assertEqual(secret_path.read_text(encoding="utf-8"), secret)
            self.assertEqual(stat.S_IMODE(secret_path.stat().st_mode) & 0o222, 0)
            self.assertIn("noswapfile", environment["EXINIT"])
            self.assertNotIn(secret, " ".join(command))
            return 0

        messages: list[str] = []
        view_secret_temporarily(
            secret,
            "/usr/bin/nano",
            runtime_root=self.runtime_root,
            launcher=inspect_editor,
            output=messages.append,
        )

        self.assertEqual(len(observed_paths), 1)
        self.assertFalse(observed_paths[0].exists())
        self.assertEqual(list(self.runtime_root.iterdir()), [])
        self.assertTrue(any("Deleted" in message for message in messages))

    def test_interrupted_editor_still_deletes_private_view(self) -> None:
        """Run cleanup before propagating an editor interruption.

        Returns:
            Nothing.
        """

        observed_path: Path | None = None

        def interrupt_editor(
            command: Sequence[str],
            environment: Mapping[str, str],
        ) -> int:
            """Capture the path and simulate Ctrl+C from the editor.

            Args:
                command: Generated editor command.
                environment: Child environment, unused by this fake.

            Raises:
                KeyboardInterrupt: Always, to exercise viewer cleanup.
            """

            nonlocal observed_path
            del environment
            observed_path = Path(command[-1])
            raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            view_secret_temporarily(
                "interrupted-value",
                "/usr/bin/vi",
                runtime_root=self.runtime_root,
                launcher=interrupt_editor,
                output=lambda message: None,
            )

        self.assertIsNotNone(observed_path)
        self.assertFalse(observed_path.exists())  # type: ignore[union-attr]
        self.assertEqual(list(self.runtime_root.iterdir()), [])

    def test_offer_can_be_declined_without_creating_a_file(self) -> None:
        """Keep the default opt-out path free of filesystem effects.

        Returns:
            Nothing.
        """

        messages: list[str] = []
        offer_temporary_secret_view(
            "declined-value",
            input_reader=lambda prompt: "",
            output=messages.append,
            locator=lambda name: f"/usr/bin/{name}",
            runtime_root=self.runtime_root,
        )

        self.assertEqual(list(self.runtime_root.iterdir()), [])
        self.assertTrue(any("skipped" in message.lower() for message in messages))

    def test_offer_uses_the_operator_selected_editor(self) -> None:
        """List installed choices and honor an explicit vim selection.

        Returns:
            Nothing.
        """

        answers = iter(("y", "2"))
        launched: list[tuple[str, ...]] = []

        def record_editor(
            command: Sequence[str],
            environment: Mapping[str, str],
        ) -> int:
            """Record the selected editor while the temporary file exists.

            Args:
                command: Generated editor command.
                environment: Child environment, unused by this fake.

            Returns:
                Successful editor exit status.
            """

            del environment
            launched.append(tuple(command))
            self.assertTrue(Path(command[-1]).is_file())
            return 0

        offer_temporary_secret_view(
            "selected-editor-value",
            input_reader=lambda prompt: next(answers),
            output=lambda message: None,
            locator=lambda name: f"/usr/bin/{name}",
            runtime_root=self.runtime_root,
            launcher=record_editor,
        )

        self.assertEqual(launched[0][0], "/usr/bin/vim")
        self.assertIn("-n", launched[0])
        self.assertEqual(list(self.runtime_root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
