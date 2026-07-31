"""
Module: test_keycloak_profile_configuration.py

Description:
    Verifies that guided Keycloak values persist through the shared deployment
    environment and stack renderer while the server trust anchor and protected
    legacy identities remain immutable.

Dependencies:
    - Python standard library.
    - Executable profile environment and Keycloak configuration modules.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIRECTORY = REPOSITORY_ROOT / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

from executable_profile import (  # noqa: E402
    ExecutableProfileError,
    load_executable_profile,
)
from executable_profile_environment import write_deployment_env  # noqa: E402
from keycloak_profile_client import (  # noqa: E402
    KeycloakProfileError,
    load_keycloak_identity,
)
from keycloak_profile_configuration import (  # noqa: E402
    KeycloakBootstrapValues,
    persist_keycloak_values,
)


class KeycloakProfileConfigurationTests(unittest.TestCase):
    """Exercise persistent, profile-safe Keycloak deployment choices."""

    def setUp(self) -> None:
        """Create one isolated configured Felix deployment.

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
        self.profile = load_executable_profile(self.root)

    def _selected_values(self) -> KeycloakBootstrapValues:
        """Build representative non-default realm/client/root selections.

        Returns:
            Selected values retaining only the tracked server URL.
        """

        defaults = KeycloakBootstrapValues.from_identity(
            load_keycloak_identity(self.profile)
        )
        return replace(
            defaults,
            realm="felix-selected",
            realm_display_name="Felix Selected",
            frontend_client_id="felix-frontend",
            backend_client_id="felix-backend",
            frontend_root_url="https://selected-felix.fe-wi.com",
            api_root_url="https://api.selected-felix.fe-wi.com",
            audience="felix-backend",
            realm_settings=(
                ("enabled", True),
                ("registrationAllowed", True),
                ("resetPasswordAllowed", False),
                ("rememberMe", False),
                ("verifyEmail", False),
                ("loginWithEmailAllowed", True),
            ),
            bootstrap_test_users_enabled=False,
        )

    def test_selected_values_persist_and_drive_runtime_and_stack(self) -> None:
        """Use entered values for Keycloak, backend runtime, and rendering.

        Returns:
            Nothing.
        """

        updated, changed = persist_keycloak_values(
            self.profile,
            self._selected_values(),
            check_compose=False,
        )
        identity = load_keycloak_identity(updated)

        self.assertTrue(changed)
        self.assertEqual(identity.realm, "felix-selected")
        self.assertEqual(identity.realm_display_name, "Felix Selected")
        self.assertEqual(identity.frontend_client_id, "felix-frontend")
        self.assertEqual(identity.backend_client_id, "felix-backend")
        self.assertEqual(identity.audience, "felix-backend")
        self.assertEqual(
            dict(identity.realm_settings),
            {
                "enabled": True,
                "registrationAllowed": True,
                "resetPasswordAllowed": False,
                "rememberMe": False,
                "verifyEmail": False,
                "loginWithEmailAllowed": True,
            },
        )
        self.assertFalse(identity.bootstrap_test_users_enabled)
        self.assertEqual(
            identity.issuer_url,
            "https://keycloak.fe-wi.com/realms/felix-selected",
        )
        self.assertIn(
            "https://selected-felix.fe-wi.com/auth/callback",
            identity.redirect_uris,
        )
        self.assertEqual(
            updated.environment["KEYCLOAK_CLIENT_ID"],
            "felix-frontend",
        )
        self.assertEqual(
            updated.environment["KEYCLOAK_ADMIN_CLIENT_ID"],
            "felix-backend",
        )
        self.assertEqual(
            updated.deployment["CORS_ORIGINS"],
            "https://selected-felix.fe-wi.com",
        )
        stack = (self.root / "swarm-stack.yml").read_text(encoding="utf-8")
        self.assertIn("felix-frontend", stack)
        self.assertIn("felix-selected", stack)

        repeated, repeated_changed = persist_keycloak_values(
            updated,
            self._selected_values(),
            check_compose=False,
        )
        self.assertFalse(repeated_changed)
        self.assertEqual(repeated.fingerprint, updated.fingerprint)

    def test_server_destination_and_legacy_identity_remain_protected(self) -> None:
        """Reject credential redirection and protected realm/client targets.

        Returns:
            Nothing.
        """

        before = (self.root / ".env").read_text(encoding="utf-8")
        selected = self._selected_values()
        with self.assertRaisesRegex(KeycloakProfileError, "trust anchor"):
            persist_keycloak_values(
                self.profile,
                replace(selected, server_url="https://untrusted.example.com"),
                check_compose=False,
            )
        with self.assertRaisesRegex(ExecutableProfileError, "protected realm"):
            persist_keycloak_values(
                self.profile,
                replace(selected, realm="felixappnew"),
                check_compose=False,
            )
        with self.assertRaisesRegex(ExecutableProfileError, "protected clients"):
            persist_keycloak_values(
                self.profile,
                replace(
                    selected,
                    frontend_client_id="felixappnew-frontend",
                ),
                check_compose=False,
            )
        self.assertEqual(
            (self.root / ".env").read_text(encoding="utf-8"),
            before,
        )

    def test_prior_environment_without_display_name_uses_profile_default(
        self,
    ) -> None:
        """Load pre-upgrade generated environments without manual migration.

        Returns:
            Nothing.
        """

        environment_path = self.root / ".env"
        retained = [
            line
            for line in environment_path.read_text(encoding="utf-8").splitlines()
            if not line.startswith("KEYCLOAK_REALM_DISPLAY_NAME=")
        ]
        environment_path.write_text(
            "\n".join(retained) + "\n",
            encoding="utf-8",
        )

        identity = load_keycloak_identity(load_executable_profile(self.root))

        self.assertEqual(identity.realm_display_name, "Felix")


if __name__ == "__main__":
    unittest.main()
