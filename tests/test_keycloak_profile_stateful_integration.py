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
from dataclasses import replace
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
    owned_field_mismatches,
    realm_payload,
)
from keycloak_profile_verification import (  # noqa: E402
    build_reconciliation_plan,
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
                bootstrap_test_user_passwords={
                    user.username: f"runtime-only-{user.username}"
                    for user in self.identity.bootstrap_test_users
                },
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
        role_count = len(self.identity.realm_roles)
        user_count = len(self.identity.bootstrap_test_users)

        self.assertEqual(
            summary["realmRolesAction"],
            f"create={role_count}",
        )
        self.assertEqual(summary["frontendAction"], "created")
        self.assertEqual(summary["backendAction"], "created")
        self.assertEqual(summary["audienceMapperAction"], "created")
        self.assertEqual(
            summary["frontendRealmRoleScopeAction"],
            "assigned",
        )
        self.assertEqual(summary["serviceAccountRolesAction"], "updated")
        self.assertEqual(
            summary["bootstrapTestUsersAction"],
            f"create={user_count}",
        )
        self.assertEqual(summary["dockerSecretAction"], "created")
        self.assertIs(summary["keycloakStateVerified"], True)
        self.assertIs(summary["dockerSecretBindingVerified"], True)
        self.assertEqual(
            summary["dockerSecretName"],
            self.identity.docker_secret,
        )
        evidence = summary["clientSecretValueEvidence"]
        self.assertIsInstance(evidence, dict)
        self.assertIs(evidence["observedThisRun"], True)
        self.assertIs(evidence["distinctFromDockerSecretName"], True)

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
        backend = self._owned_client(self.identity.backend_client_id)
        self.assertEqual(
            owned_field_mismatches(backend, backend_payload(self.identity)),
            (),
        )
        self.assertEqual(
            backend["redirectUris"],
            [f"{self.identity.api_root_url}/*"],
        )
        self.assertEqual(
            backend["webOrigins"],
            [self.identity.api_root_url],
        )
        self.assertEqual(self.client.assignment_roles, {"manage-users"})
        self.assertEqual(self.client.scope_roles, {"manage-users"})
        self.assertEqual(
            set(self.client.application_access.realm_roles),
            {role.name for role in self.identity.realm_roles},
        )
        self.assertEqual(
            self.client.frontend_scope_roles,
            {role.name for role in self.identity.realm_roles},
        )
        self.assertEqual(
            set(self.client.application_access.users),
            {user.username for user in self.identity.bootstrap_test_users},
        )
        self.assertEqual(
            self.client.application_access.passwords_set,
            set(self.client.application_access.users),
        )
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
            Client representation without the fake's internal UUID.
        """

        current = dict(self.client.clients[client_id])
        current.pop("id")
        return current

    def test_disabling_test_users_requires_explicit_production_cleanup(
        self,
    ) -> None:
        """Block production desired state until temporary users are removed.

        Returns:
            Nothing.
        """

        self._run_bootstrap()
        self.client.identity = replace(
            self.identity,
            bootstrap_test_users_enabled=False,
        )

        plan = build_reconciliation_plan(
            self.client,
            docker_secret_present=True,
            replace_secret=False,
        )

        cleanup = [
            blocker
            for blocker in plan["blockers"]
            if "Delete bootstrap test user before production" in blocker
        ]
        self.assertEqual(len(cleanup), len(self.identity.bootstrap_test_users))

    def test_skipping_one_declared_user_requires_only_its_cleanup(self) -> None:
        """Apply the per-user lifecycle without disabling selected users.

        Returns:
            Nothing.
        """

        self._run_bootstrap()
        skipped_username = self.identity.bootstrap_test_users[-1].username
        selected_users = tuple(
            replace(
                user,
                selected_for_bootstrap=(user.username != skipped_username),
            )
            for user in self.identity.bootstrap_test_users
        )
        self.client.identity = replace(
            self.identity,
            bootstrap_test_users=selected_users,
        )

        plan = build_reconciliation_plan(
            self.client,
            docker_secret_present=True,
            replace_secret=False,
        )

        cleanup = [
            blocker
            for blocker in plan["blockers"]
            if "Delete bootstrap test user before production" in blocker
        ]
        self.assertEqual(
            cleanup,
            [
                "Delete bootstrap test user before production: "
                f"{skipped_username}"
            ],
        )

    def test_disabled_realm_blocks_a_new_secret_proof(self) -> None:
        """Require an enabled realm while creating the backend credential.

        Returns:
            Nothing.
        """

        settings = tuple(
            (name, False if name == "enabled" else value)
            for name, value in self.identity.realm_settings
        )
        self.client.identity = replace(
            self.identity,
            realm_settings=settings,
        )

        plan = build_reconciliation_plan(
            self.client,
            docker_secret_present=False,
            replace_secret=False,
        )

        self.assertIn(
            "Enable the realm for one bootstrap run before creating or "
            "rotating the proven Docker client secret.",
            plan["blockers"],
        )

    def test_repeated_bootstrap_keeps_roles_users_and_frontend_scope(self) -> None:
        """Require application-access reconciliation to be idempotent.

        Returns:
            Nothing.
        """

        self._run_bootstrap()
        summary, _ = self._run_bootstrap()
        role_count = len(self.identity.realm_roles)
        user_count = len(self.identity.bootstrap_test_users)

        self.assertEqual(summary["realmAction"], "kept")
        self.assertEqual(summary["realmRolesAction"], f"keep={role_count}")
        self.assertEqual(summary["frontendAction"], "kept")
        self.assertEqual(summary["backendAction"], "kept")
        self.assertEqual(summary["audienceMapperAction"], "kept")
        self.assertEqual(summary["frontendRealmRoleScopeAction"], "kept")
        self.assertEqual(summary["serviceAccountRolesAction"], "kept")
        self.assertEqual(
            summary["bootstrapTestUsersAction"],
            f"keep={user_count}",
        )

    def test_selected_role_subset_removes_obsolete_user_and_scope_mappings(
        self,
    ) -> None:
        """Make the chosen role subset exact without deleting realm roles.

        Returns:
            Nothing.
        """

        self._run_bootstrap()
        self.assertGreaterEqual(len(self.identity.realm_roles), 2)
        original_role_names = {
            role.name for role in self.identity.realm_roles
        }
        selected_role_name = self.identity.realm_roles[0].name
        role_names = {selected_role_name}
        selected_roles = tuple(
            role for role in self.identity.realm_roles if role.name in role_names
        )
        selected_users = tuple(
            replace(
                user,
                realm_roles=tuple(
                    role for role in user.realm_roles if role in role_names
                )
                or (selected_role_name,),
            )
            for user in self.identity.bootstrap_test_users
        )
        self.identity = replace(
            self.identity,
            realm_roles=selected_roles,
            bootstrap_test_users=selected_users,
        )
        self.client.identity = self.identity

        summary, _ = self._run_bootstrap()

        self.assertEqual(
            summary["frontendRealmRoleScopeAction"],
            "reconciled",
        )
        self.assertEqual(self.client.frontend_scope_roles, role_names)
        self.assertEqual(
            set(self.client.application_access.realm_roles),
            original_role_names,
        )
        for user in selected_users:
            user_uuid = self.client.application_access.users[user.username]["id"]
            self.assertEqual(
                self.client.application_access.user_roles[user_uuid],
                set(user.realm_roles),
            )

    def test_existing_user_without_password_is_recovered(self) -> None:
        """Detect and repair a partial user-creation result on a later run.

        Returns:
            Nothing.
        """

        self._run_bootstrap()
        recovered_username = self.identity.bootstrap_test_users[-1].username
        self.client.application_access.passwords_set.remove(
            recovered_username
        )

        plan = build_reconciliation_plan(
            self.client,
            docker_secret_present=True,
            replace_secret=False,
        )

        self.assertEqual(
            plan["bootstrapTestUserActions"][recovered_username],
            "set-password",
        )
        summary, _ = self._run_bootstrap()
        kept_count = len(self.identity.bootstrap_test_users) - 1
        self.assertEqual(
            summary["bootstrapTestUsersAction"],
            f"keep={kept_count}, set-password=1",
        )
        self.assertIn(
            recovered_username,
            self.client.application_access.passwords_set,
        )

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
        recorded_requests = json.dumps(self.client.requests)
        self.assertNotIn(self.secret, visible)
        self.assertNotIn(self.secret, request_urls)
        self.assertNotIn("runtime-only-", recorded_requests)

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
