"""
Module: test_keycloak_profile_secret_handoff.py

Description:
    Verifies Keycloak client-secret rotation, credential proof ordering,
    Docker handoff decisions, and pre-mutation stack safety independently
    from realm/client representation reconciliation.

Dependencies:
    - Python standard library.
    - Shared executable-profile and Keycloak bootstrap modules.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIRECTORY = REPOSITORY_ROOT / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

from executable_profile import load_executable_profile  # noqa: E402
from executable_profile_environment import (  # noqa: E402
    write_deployment_env,
)
from keycloak_profile_bootstrap import (  # noqa: E402
    KeycloakProfileError,
    load_keycloak_identity,
    reconcile,
    reconcile_authenticated,
    regenerate_client_secret,
)
from tests.keycloak_profile_test_support import (  # noqa: E402
    RecordingAdminClient,
)


class KeycloakProfileSecretHandoffTests(unittest.TestCase):
    """Exercise secret-only bootstrap and rotation orchestration boundaries."""

    def setUp(self) -> None:
        """Create one isolated configured executable profile.

        Returns:
            Nothing.
        """

        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        config_directory = self.root / "site-configs"
        config_directory.mkdir()
        profile_data = json.loads(
            (REPOSITORY_ROOT / "site-configs" / "felix.json").read_text(
                encoding="utf-8"
            )
        )
        (config_directory / "felix.json").write_text(
            json.dumps(profile_data, indent=2) + "\n",
            encoding="utf-8",
        )
        write_deployment_env(self.root, "felix", {}, force=True)
        self.profile = load_executable_profile(self.root)
        self.identity = load_keycloak_identity(self.profile)

    def _bootstrap_replacements(
        self,
        admin_client: Mock,
        docker_secret_present: bool,
        boundaries: dict[str, Mock],
    ) -> dict[str, Mock]:
        """Build patched bootstrap boundaries for one orchestration test.

        Args:
            admin_client: Fake authenticated Keycloak client.
            docker_secret_present: Whether Docker reports the target secret.
            boundaries: Named plan, verification, secret, and write mocks.

        Returns:
            Keyword replacements accepted by ``patch.multiple``.
        """

        return {
            "stack_is_running": Mock(return_value=False),
            "docker_secret_exists": Mock(
                return_value=docker_secret_present,
            ),
            "build_reconciliation_plan": boundaries["buildPlan"],
            "verify_reconciled_state": boundaries["verifyState"],
            "KeycloakAdminClient": Mock(return_value=admin_client),
            "ensure_realm": Mock(return_value="kept"),
            "ensure_realm_roles": Mock(return_value="keep=4"),
            "_resolve_client_uuid": Mock(return_value="backend-uuid"),
            "ensure_client": Mock(
                side_effect=[
                    ("frontend-uuid", "kept"),
                    ("backend-uuid", "kept"),
                ]
            ),
            "ensure_audience_mapper": Mock(return_value="kept"),
            "ensure_frontend_realm_role_scope": Mock(return_value="kept"),
            "ensure_service_account_roles": Mock(return_value="kept"),
            "ensure_bootstrap_test_users": Mock(return_value="keep=4"),
            "get_client_secret": boundaries["getSecret"],
            "regenerate_client_secret": boundaries["rotateSecret"],
            "write_docker_secret": boundaries["writeSecret"],
        }

    def _run_mocked_reconcile(
        self,
        *,
        docker_secret_present: bool,
        replace_secret: bool,
        current_secret: str | None = None,
        rotated_secret: str | None = None,
        docker_action: str = "present-unverified",
        proof_effect: Callable[[str, str], None] | None = None,
        write_effect: Callable[..., str] | None = None,
        secret_observer: Callable[[str], None] | None = None,
    ) -> tuple[dict[str, object], Mock, dict[str, Mock]]:
        """Run bootstrap orchestration with deterministic external boundaries.

        Args:
            docker_secret_present: Whether Docker reports the secret.
            replace_secret: Whether reconciliation requests rotation.
            current_secret: Keycloak value returned by a normal secret read.
            rotated_secret: Keycloak value returned after rotation.
            docker_action: Docker bridge result when it is invoked.
            proof_effect: Optional client-credentials proof callback.
            write_effect: Optional Docker-write callback.
            secret_observer: Optional runtime-only recovery-view callback.

        Returns:
            Summary, fake Admin client, and inspectable boundary mocks.
        """

        admin_client = Mock(identity=self.identity)
        admin_client.prove_client_credentials.side_effect = proof_effect
        boundaries = {
            "buildPlan": Mock(return_value={"blockers": []}),
            "getSecret": Mock(return_value=current_secret),
            "rotateSecret": Mock(return_value=rotated_secret),
            "verifyState": Mock(return_value={"converged": True}),
            "writeSecret": Mock(
                return_value=docker_action,
                side_effect=write_effect,
            ),
        }
        replacements = self._bootstrap_replacements(
            admin_client,
            docker_secret_present,
            boundaries,
        )
        with patch.multiple("keycloak_profile_bootstrap", **replacements):
            summary = reconcile(
                self.profile,
                "admin",
                "admin-password",
                replace_secret=replace_secret,
                secret_observer=secret_observer,
            )
        return summary, admin_client, boundaries

    def test_regeneration_uses_keycloak_rotation_endpoint(self) -> None:
        """Return a rotated secret from POST without placing it in a URL.

        Returns:
            Nothing.
        """

        def handler(
            method: str,
            path: str,
            body: Any,
            query: dict[str, str] | None,
            expected: tuple[int, ...],
        ) -> tuple[int, Any]:
            """Return a secret only from the rotation endpoint."""

            self.assertEqual(method, "POST")
            self.assertTrue(path.endswith("/client-secret"))
            self.assertIsNone(body)
            return 200, {"value": "rotated-sensitive-value"}

        client = RecordingAdminClient(self.identity, handler)
        secret = regenerate_client_secret(client, "backend-uuid")

        self.assertEqual(secret, "rotated-sensitive-value")
        self.assertNotIn(
            secret,
            " ".join(path for _, path, _, _ in client.requests),
        )

    def test_explicit_rotation_replaces_docker_secret(self) -> None:
        """Bind a newly rotated Keycloak value to the exact Docker secret.

        Returns:
            Nothing.
        """

        summary, admin_client, boundaries = self._run_mocked_reconcile(
            docker_secret_present=True,
            replace_secret=True,
            rotated_secret="new-sensitive-value",
            docker_action="replaced",
        )

        boundaries["getSecret"].assert_not_called()
        boundaries["rotateSecret"].assert_called_once_with(
            admin_client,
            "backend-uuid",
        )
        boundaries["buildPlan"].assert_called_once_with(
            admin_client,
            docker_secret_present=True,
            replace_secret=True,
        )
        boundaries["verifyState"].assert_called_once_with(admin_client)
        admin_client.prove_client_credentials.assert_called_once_with(
            self.identity.backend_client_id,
            "new-sensitive-value",
        )
        boundaries["writeSecret"].assert_called_once_with(
            self.profile,
            self.identity,
            "new-sensitive-value",
            replace=True,
        )
        self.assertEqual(summary["dockerSecretAction"], "replaced")
        self.assertIs(summary["dockerSecretBindingVerified"], True)
        self.assertNotIn("new-sensitive-value", json.dumps(summary))

    def test_running_stack_blocks_rotation_before_realm_mutation(
        self,
    ) -> None:
        """Reject rotation before applying even harmless-looking realm drift.

        Returns:
            Nothing.
        """

        client = Mock(identity=self.identity)
        with (
            patch(
                "keycloak_profile_bootstrap.build_reconciliation_plan",
                return_value={"blockers": []},
            ),
            patch(
                "keycloak_profile_bootstrap.stack_is_running",
                return_value=True,
            ),
            patch(
                "keycloak_profile_bootstrap.docker_secret_exists",
                return_value=True,
            ),
            patch(
                "keycloak_profile_bootstrap.ensure_realm"
            ) as ensure_realm_mock,
            self.assertRaisesRegex(
                KeycloakProfileError,
                "Stop the selected stack",
            ),
        ):
            reconcile_authenticated(
                self.profile,
                client,
                replace_secret=True,
                docker_secret_present=True,
            )

        ensure_realm_mock.assert_not_called()

    def test_missing_secret_is_proved_before_docker_write(self) -> None:
        """Prove Keycloak's returned secret before piping it to Docker.

        Returns:
            Nothing.
        """

        secret_value = "keycloak-returned-sensitive-sentinel"
        events: list[str] = []

        def record_proof(client_id: str, secret: str) -> None:
            """Record credential proof without exposing the sentinel."""

            self.assertEqual(client_id, self.identity.backend_client_id)
            self.assertEqual(secret, secret_value)
            events.append("proved")

        def record_write(
            profile: object,
            identity: object,
            secret: str,
            *,
            replace: bool,
        ) -> str:
            """Record Docker write and require the exact proven value."""

            self.assertIs(profile, self.profile)
            self.assertIs(identity, self.identity)
            self.assertEqual(secret, secret_value)
            self.assertIs(replace, False)
            events.append("written")
            return "created"

        summary, admin_client, boundaries = self._run_mocked_reconcile(
            docker_secret_present=False,
            replace_secret=False,
            current_secret=secret_value,
            docker_action="created",
            proof_effect=record_proof,
            write_effect=record_write,
        )

        boundaries["getSecret"].assert_called_once_with(
            admin_client,
            "backend-uuid",
        )
        boundaries["rotateSecret"].assert_not_called()
        boundaries["buildPlan"].assert_called_once_with(
            admin_client,
            docker_secret_present=False,
            replace_secret=False,
        )
        boundaries["verifyState"].assert_called_once_with(admin_client)
        self.assertEqual(events, ["proved", "written"])
        self.assertEqual(summary["dockerSecretAction"], "created")
        self.assertIs(summary["dockerSecretBindingVerified"], True)
        self.assertEqual(
            summary["dockerSecretName"],
            self.identity.docker_secret,
        )
        self.assertNotIn("dockerSecret", summary)
        evidence = summary["clientSecretValueEvidence"]
        self.assertIsInstance(evidence, dict)
        self.assertIs(evidence["observedThisRun"], True)
        self.assertIs(evidence["distinctFromDockerSecretName"], True)
        self.assertEqual(evidence["length"], len(secret_value))
        self.assertNotIn(secret_value, json.dumps(summary))

    def test_new_secret_is_offered_only_after_successful_docker_write(self) -> None:
        """Expose the real value to a runtime observer after its exact write.

        Returns:
            Nothing.
        """

        secret_value = "keycloak-returned-recovery-sentinel"
        events: list[str] = []

        def record_write(
            profile: object,
            identity: object,
            secret: str,
            *,
            replace: bool,
        ) -> str:
            """Record the proven Docker write before recovery viewing.

            Args:
                profile: Selected executable profile.
                identity: Selected Keycloak identity.
                secret: Exact secret being stored.
                replace: Whether the fixed-name secret is replaced.

            Returns:
                Docker bridge action.
            """

            del profile, identity, replace
            self.assertEqual(secret, secret_value)
            events.append("written")
            return "created"

        def observe(secret: str) -> None:
            """Require the observer to receive the exact post-write value.

            Args:
                secret: Exact newly stored Keycloak credential.

            Returns:
                Nothing.
            """

            self.assertEqual(secret, secret_value)
            events.append("observed")

        summary, _, _ = self._run_mocked_reconcile(
            docker_secret_present=False,
            replace_secret=False,
            current_secret=secret_value,
            docker_action="created",
            write_effect=record_write,
            secret_observer=observe,
        )

        self.assertEqual(events, ["written", "observed"])
        self.assertEqual(summary["dockerSecretAction"], "created")
        self.assertNotIn(secret_value, json.dumps(summary))

    def test_existing_docker_secret_remains_opaque(self) -> None:
        """Report an existing opaque Docker secret as unverified.

        Returns:
            Nothing.
        """

        observer = Mock()
        summary, admin_client, boundaries = self._run_mocked_reconcile(
            docker_secret_present=True,
            replace_secret=False,
            secret_observer=observer,
        )

        self.assertEqual(
            summary["dockerSecretAction"],
            "present-unverified",
        )
        self.assertIs(summary["dockerSecretBindingVerified"], False)
        evidence = summary["clientSecretValueEvidence"]
        self.assertIsInstance(evidence, dict)
        self.assertIs(evidence["observedThisRun"], False)
        self.assertIsNone(evidence["sha256Prefix"])
        boundaries["buildPlan"].assert_called_once_with(
            admin_client,
            docker_secret_present=True,
            replace_secret=False,
        )
        boundaries["verifyState"].assert_called_once_with(admin_client)
        boundaries["getSecret"].assert_not_called()
        boundaries["rotateSecret"].assert_not_called()
        boundaries["writeSecret"].assert_not_called()
        admin_client.prove_client_credentials.assert_not_called()
        observer.assert_not_called()
        self.assertNotIn("admin-password", json.dumps(summary))


if __name__ == "__main__":
    unittest.main()
