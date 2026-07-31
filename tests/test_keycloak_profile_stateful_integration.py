"""
Module: test_keycloak_profile_stateful_integration.py

Description:
    Exercises the complete fresh-realm Keycloak reconciliation path against a
    mutable fake server while replacing only Docker Swarm boundaries.

Dependencies:
    - Python standard library.
    - Shared executable-profile and Keycloak bootstrap modules.
    - tests/keycloak_profile_stateful_support.py.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIRECTORY = REPOSITORY_ROOT / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

from executable_profile import load_executable_profile  # noqa: E402
from executable_profile_environment import (  # noqa: E402
    write_deployment_env,
)
from keycloak_profile_bootstrap import (  # noqa: E402
    reconcile_authenticated,
)
from keycloak_profile_client import load_keycloak_identity  # noqa: E402
from keycloak_profile_reconciliation import (  # noqa: E402
    backend_payload,
    frontend_payload,
    realm_payload,
)
from tests.keycloak_profile_stateful_support import (  # noqa: E402
    StatefulKeycloakAdminClient,
)


class KeycloakProfileStatefulIntegrationTests(unittest.TestCase):
    """Verify one complete missing-realm bootstrap and secret handoff."""

    def setUp(self) -> None:
        """Create an isolated executable Felix profile and empty fake server.

        Returns:
            Nothing.
        """

        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        config_directory = self.root / "site-configs"
        config_directory.mkdir()
        source = REPOSITORY_ROOT / "site-configs" / "felix.json"
        profile_data = json.loads(source.read_text(encoding="utf-8"))
        target = config_directory / "felix.json"
        target.write_text(
            json.dumps(profile_data, indent=2) + "\n",
            encoding="utf-8",
        )
        write_deployment_env(self.root, "felix", {}, force=True)
        self.profile = load_executable_profile(self.root)
        self.identity = load_keycloak_identity(self.profile)
        self.secret = "keycloak-stateful-secret-sentinel"
        self.client = StatefulKeycloakAdminClient(
            self.identity,
            self.secret,
        )

    def _run_bootstrap(self) -> tuple[dict[str, object], list[str]]:
        """Run production reconciliation with only Docker calls replaced.

        Returns:
            Secret-free summary and captured progress messages.
        """

        progress: list[str] = []

        def write_secret(profile, identity, secret, *, replace):
            """Record the exact proven Keycloak value sent to Docker.

            Args:
                profile: Active executable deployment profile.
                identity: Profile-derived Keycloak identity.
                secret: Credential returned and proved by Keycloak.
                replace: Whether an existing Docker secret may be replaced.

            Returns:
                ``created`` after validating the in-memory handoff.
            """

            self.assertIs(profile, self.profile)
            self.assertIs(identity, self.identity)
            self.assertEqual(secret, self.secret)
            self.assertIs(replace, False)
            self.assertEqual(self.client.events[-1], "proof")
            self.client.events.append("write")
            return "created"

        with (
            patch(
                "keycloak_profile_bootstrap.docker_secret_exists",
                return_value=False,
            ),
            patch(
                "keycloak_profile_bootstrap.stack_is_running",
                return_value=False,
            ),
            patch(
                "keycloak_profile_bootstrap.write_docker_secret",
                side_effect=write_secret,
            ),
        ):
            summary = reconcile_authenticated(
                self.profile,
                self.client,
                replace_secret=False,
                docker_secret_present=False,
                progress=progress.append,
            )
        return summary, progress

    def _assert_summary(self, summary: dict[str, object]) -> None:
        """Require fresh-resource actions and a verified Docker binding.

        Args:
            summary: Production bootstrap result.

        Returns:
            Nothing.
        """

        self.assertEqual(summary["realmAction"], "created")
        self.assertEqual(summary["frontendAction"], "created")
        self.assertEqual(summary["backendAction"], "created")
        self.assertEqual(summary["audienceMapperAction"], "created")
        self.assertEqual(summary["serviceAccountRolesAction"], "updated")
        self.assertEqual(summary["dockerSecretAction"], "created")
        self.assertIs(summary["keycloakStateVerified"], True)
        self.assertIs(summary["dockerSecretBindingVerified"], True)

    def _assert_reconciled_state(self) -> None:
        """Require exact read-back state, role assignment, and client scope.

        Returns:
            Nothing.
        """

        self.assertEqual(self.client.realm, realm_payload(self.identity))
        self.assertEqual(
            self._owned_client(self.identity.frontend_client_id),
            frontend_payload(self.identity),
        )
        self.assertEqual(
            self._owned_client(self.identity.backend_client_id),
            backend_payload(self.identity),
        )
        self.assertEqual(self.client.assignment_roles, {"manage-users"})
        self.assertEqual(self.client.scope_roles, {"manage-users"})
        self.assertEqual(
            self.client.events,
            ["secret-read", "proof", "write"],
        )
        self.assertEqual(
            set(self.client.public_requests),
            {
                (
                    f"{self.identity.issuer_url}/"
                    ".well-known/openid-configuration"
                ),
                self.identity.jwks_url,
            },
        )

    def _owned_client(self, client_id: str) -> dict[str, object]:
        """Remove the fake internal UUID from one client representation.

        Args:
            client_id: Public client identifier.

        Returns:
            Profile-owned client representation.
        """

        current = dict(self.client.clients[client_id])
        current.pop("id")
        return current

    def _assert_secret_hygiene(
        self,
        summary: dict[str, object],
        progress: list[str],
    ) -> None:
        """Require the secret to remain absent from observable output.

        Args:
            summary: Production bootstrap summary.
            progress: Captured operator progress lines.

        Returns:
            Nothing.
        """

        visible = json.dumps(summary) + "\n" + "\n".join(progress)
        request_urls = "\n".join(
            path for _, path, _, _ in self.client.requests
        )
        self.assertNotIn(self.secret, visible)
        self.assertNotIn(self.secret, request_urls)

    def test_missing_realm_is_verified_before_real_secret_write(self) -> None:
        """Create, verify, prove, and bridge a complete fresh realm.

        Returns:
            Nothing.
        """

        summary, progress = self._run_bootstrap()

        self._assert_summary(summary)
        self._assert_reconciled_state()
        self._assert_secret_hygiene(summary, progress)


if __name__ == "__main__":
    unittest.main()
