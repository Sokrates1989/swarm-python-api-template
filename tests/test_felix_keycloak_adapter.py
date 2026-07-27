"""Tests for the pinned, secret-safe Felix Keycloak Swarm adapter."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import felix_keycloak_adapter as adapter


PIN_PATH = (
    Path("docs")
    / "release_contracts"
    / "felix_keycloak_tool.v1.json"
)


class FelixKeycloakAdapterTests(unittest.TestCase):
    """Verify exact pinning and credential-free delegated arguments."""

    def test_committed_pin_matches_candidate_and_canonical_commit(self) -> None:
        """Load the exact candidate identities and source revision."""

        pin = adapter.load_pin(PIN_PATH)

        self.assertEqual(pin["sourceCommit"], adapter.EXPECTED_COMMIT)
        self.assertEqual(pin["candidateRealm"], "felix-new")
        self.assertEqual(pin["frontendClientId"], "felix-new-frontend")
        self.assertEqual(pin["backendClientId"], "felix-new-backend")

    def test_delegate_command_contains_password_path_not_value(self) -> None:
        """Build command arguments without ever reading credential content."""

        entrypoint = Path("/canonical/tools/felix_keycloak.py")
        password_file = Path("/run/secrets/keycloak_admin_password")

        command = adapter.build_delegate_command(
            entrypoint,
            "apply",
            "Patrick",
            password_file,
        )

        self.assertEqual(command[0], sys.executable)
        self.assertIn(str(password_file), command)
        self.assertNotIn("admin-password-value", command)

    def test_rotation_requires_separate_exact_confirmation(self) -> None:
        """Reject rotation without the exact backend client acknowledgement."""

        with self.assertRaises(adapter.AdapterError):
            adapter.build_delegate_command(
                Path("/canonical/tools/felix_keycloak.py"),
                "rotate-secret",
                "Patrick",
                Path("/run/secrets/keycloak_admin_password"),
                rotation_secret_name="FELIX_NEW_KEYCLOAK_ADMIN_CLIENT_SECRET_v2",
                rotation_confirmation="wrong-client",
            )

    def test_pin_rejects_legacy_target_collision(self) -> None:
        """Refuse a pin that substitutes a protected legacy realm."""

        raw = json.loads(PIN_PATH.read_text(encoding="utf-8"))
        raw["candidateRealm"] = "felix"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe-pin.json"
            path.write_text(json.dumps(raw), encoding="utf-8")

            with self.assertRaises(adapter.AdapterError):
                adapter.load_pin(path)

    @mock.patch.object(adapter.subprocess, "run")
    def test_checkout_validation_requires_exact_clean_commit(
        self,
        run: mock.Mock,
    ) -> None:
        """Accept only a clean checkout with the pinned CLI version."""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entrypoint = root / "tools" / "felix_keycloak.py"
            entrypoint.parent.mkdir()
            entrypoint.write_text("# test entrypoint\n", encoding="utf-8")
            run.side_effect = [
                mock.Mock(returncode=0, stdout=f"{adapter.EXPECTED_COMMIT}\n"),
                mock.Mock(returncode=0, stdout=""),
                mock.Mock(returncode=0, stdout=f"{adapter.EXPECTED_VERSION}\n"),
            ]

            resolved = adapter.validate_tool_checkout(
                root,
                adapter.load_pin(PIN_PATH),
            )

        self.assertEqual(resolved, entrypoint.resolve())


if __name__ == "__main__":
    unittest.main()
