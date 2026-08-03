"""
Module: test_keycloak_profile_cleanup.py

Description:
    Verifies provenance-safe tracking and non-destructive acknowledgement of
    temporary Keycloak users created by the shared bootstrap.

Dependencies:
    - Python standard library.
    - Executable profile environment and Keycloak cleanup modules.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIRECTORY = REPOSITORY_ROOT / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

from executable_profile import load_executable_profile  # noqa: E402
from executable_profile_environment import write_deployment_env  # noqa: E402
from keycloak_profile_cleanup import (  # noqa: E402
    acknowledge_bootstrap_user_cleanup,
    read_bootstrap_user_cleanup_state,
    record_created_bootstrap_users,
)


class KeycloakProfileCleanupTests(unittest.TestCase):
    """Exercise public cleanup state without any Keycloak dependency."""

    def setUp(self) -> None:
        """Create one isolated configured executable deployment.

        Returns:
            Nothing.
        """

        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        configs = self.root / "site-configs"
        configs.mkdir()
        source = REPOSITORY_ROOT / "site-configs" / "felix.json"
        (configs / "felix.json").write_text(
            source.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        write_deployment_env(self.root, "felix", {}, force=True)

    def test_only_verified_create_actions_become_cleanup_reminders(self) -> None:
        """Exclude skipped, kept, and updated users from tool ownership.

        Returns:
            Nothing.
        """

        environment = self.root / ".env"
        source = environment.read_text(encoding="utf-8")
        environment.write_text(
            source.replace(
                "KEYCLOAK_BOOTSTRAP_TEST_USERS_ENABLED=",
                "# Human-readable authentication state.\n"
                "KEYCLOAK_BOOTSTRAP_TEST_USERS_ENABLED=",
            ),
            encoding="utf-8",
        )
        profile = load_executable_profile(self.root)
        prior_fingerprint = profile.fingerprint
        state = record_created_bootstrap_users(
            profile,
            {
                "bootstrapTestUserActions": {
                    "created-user": "create",
                    "existing-user": "update",
                    "untouched-user": "skip",
                    "stable-user": "keep",
                }
            },
        )

        reloaded = load_executable_profile(self.root)
        persisted = read_bootstrap_user_cleanup_state(reloaded)
        content = environment.read_text(encoding="utf-8")
        self.assertEqual(state, persisted)
        self.assertEqual(reloaded.fingerprint, prior_fingerprint)
        self.assertTrue(persisted.pending)
        self.assertEqual(persisted.usernames, ("created-user",))
        self.assertIn("# Human-readable authentication state.", content)
        self.assertIn(
            "KEYCLOAK_BOOTSTRAP_USERS_CLEANUP_PENDING=true",
            content,
        )

    def test_created_users_accumulate_until_operator_acknowledgement(self) -> None:
        """Retain earlier reminders and clear them only through acknowledgement.

        Returns:
            Nothing.
        """

        first = record_created_bootstrap_users(
            load_executable_profile(self.root),
            {"bootstrapTestUserActions": {"test-admin": "create"}},
        )
        second = record_created_bootstrap_users(
            load_executable_profile(self.root),
            {
                "bootstrapTestUserActions": {
                    "test-admin": "keep",
                    "test-user": "create",
                }
            },
        )
        prior = acknowledge_bootstrap_user_cleanup(
            load_executable_profile(self.root)
        )
        cleared = read_bootstrap_user_cleanup_state(
            load_executable_profile(self.root)
        )

        self.assertEqual(first.usernames, ("test-admin",))
        self.assertEqual(second.usernames, ("test-admin", "test-user"))
        self.assertEqual(prior, second)
        self.assertFalse(cleared.pending)
        self.assertEqual(cleared.usernames, ())

    def test_existing_or_self_registered_user_is_never_inferred(self) -> None:
        """Do not track a reserved-name account unless this run created it.

        Returns:
            Nothing.
        """

        state = record_created_bootstrap_users(
            load_executable_profile(self.root),
            {
                "bootstrapTestUserActions": {
                    "test": "skip",
                    "registered-user": "keep",
                }
            },
        )

        self.assertFalse(state.pending)
        self.assertEqual(state.usernames, ())


if __name__ == "__main__":
    unittest.main()
