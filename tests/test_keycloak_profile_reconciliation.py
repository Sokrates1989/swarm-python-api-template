"""
Module: test_keycloak_profile_reconciliation.py

Description:
    Verifies generic Keycloak client idempotency, exact service-account roles,
    protected identity validation, true client-secret rotation, and the
    in-memory Docker secret handoff decision.

Dependencies:
    - Python standard library.
    - Shared executable-profile and Keycloak reconciliation modules.
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIRECTORY = REPOSITORY_ROOT / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

from executable_profile import (  # noqa: E402
    ExecutableProfileError,
    load_executable_profile,
)
from executable_profile_environment import (  # noqa: E402
    load_config_defaults,
    write_deployment_env,
)
from keycloak_profile_bootstrap import (  # noqa: E402
    KeycloakIdentity,
    _frontend_payload,
    ensure_client,
    load_keycloak_identity,
    reconcile,
    regenerate_client_secret,
)
from keycloak_profile_roles import (  # noqa: E402
    KeycloakRoleError,
    ensure_service_account_roles,
)


class RecordingAdminClient:
    """Provide deterministic Keycloak Admin responses and request evidence."""

    def __init__(
        self,
        identity: KeycloakIdentity,
        handler,
    ) -> None:
        """Create one request-recording fake client.

        Args:
            identity: Profile-derived Keycloak identity.
            handler: Callable returning ``(status, payload)`` for a request.

        Returns:
            Nothing.
        """

        self.identity = identity
        self.handler = handler
        self.requests: list[tuple[str, str, Any, Any]] = []

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Any | None = None,
        query: dict[str, str] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> tuple[int, Any]:
        """Record and dispatch one fake Admin API request.

        Args:
            method: HTTP method.
            path: Admin API path.
            body: Optional JSON-compatible body.
            query: Optional query mapping.
            expected: Accepted status codes.

        Returns:
            Handler-provided status and payload.
        """

        self.requests.append((method, path, body, query))
        return self.handler(method, path, body, query, expected)


class KeycloakProfileReconciliationTests(unittest.TestCase):
    """Exercise profile-only Keycloak reconciliation and secret decisions."""

    def setUp(self) -> None:
        """Create one isolated configured executable profile.

        Returns:
            Nothing.
        """

        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        config_directory = self.root / "site-configs"
        config_directory.mkdir()
        self.profile_data = json.loads(
            (REPOSITORY_ROOT / "site-configs" / "felix.json").read_text(
                encoding="utf-8"
            )
        )
        (config_directory / "felix.json").write_text(
            json.dumps(self.profile_data, indent=2) + "\n",
            encoding="utf-8",
        )
        write_deployment_env(self.root, "felix", {}, force=True)
        self.profile = load_executable_profile(self.root)
        self.identity = load_keycloak_identity(self.profile)

    def tearDown(self) -> None:
        """Remove the isolated profile root.

        Returns:
            Nothing.
        """

        self.temporary.cleanup()

    def test_profile_drives_protected_identity_and_service_account_role(
        self,
    ) -> None:
        """Load least-privilege roles and reject a protected target realm.

        Returns:
            Nothing.
        """

        self.assertEqual(
            self.identity.service_account_client_roles,
            (("realm-management", ("manage-users",)),),
        )
        invalid = copy.deepcopy(self.profile_data)
        invalid["auth"]["realm"] = "felixappnew"
        invalid["auth"]["issuerUrl"] = (
            "https://keycloak.fe-wi.com/realms/felixappnew"
        )
        invalid["auth"]["jwksUrl"] = (
            "https://keycloak.fe-wi.com/realms/felixappnew/"
            "protocol/openid-connect/certs"
        )
        (self.root / "site-configs" / "felix.json").write_text(
            json.dumps(invalid, indent=2) + "\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            ExecutableProfileError,
            "protected realm",
        ):
            load_config_defaults(self.root, "felix")

    def test_existing_frontend_client_is_kept_without_put(self) -> None:
        """Avoid a Keycloak write when all profile-owned fields already match.

        Returns:
            Nothing.
        """

        desired = _frontend_payload(self.identity)
        existing = {
            "id": "frontend-uuid",
            **desired,
            "attributes": {
                **desired["attributes"],
                "unrelated.setting": "preserved",
            },
        }

        def handler(method, path, body, query, expected):
            """Return client lookup and representation fixtures."""

            if query:
                return 200, [
                    {
                        "id": "frontend-uuid",
                        "clientId": self.identity.frontend_client_id,
                    }
                ]
            if method == "GET":
                return 200, existing
            self.fail(f"Unexpected write: {method} {path}")

        client = RecordingAdminClient(self.identity, handler)
        client_uuid, action = ensure_client(client, desired)

        self.assertEqual(client_uuid, "frontend-uuid")
        self.assertEqual(action, "kept")
        self.assertFalse(
            any(method == "PUT" for method, _, _, _ in client.requests)
        )

    def test_service_account_role_is_added_once(self) -> None:
        """Add the one declared role without broadening the grant set.

        Returns:
            Nothing.
        """

        def handler(method, path, body, query, expected):
            """Return deterministic service-account and role fixtures."""

            if path.endswith("/service-account-user"):
                return 200, {"id": "service-user"}
            if query == {"clientId": "realm-management"}:
                return 200, [
                    {
                        "id": "realm-management-uuid",
                        "clientId": "realm-management",
                    }
                ]
            if path.endswith("/role-mappings/clients/realm-management-uuid"):
                if method == "GET":
                    return 200, []
                return 204, None
            if path.endswith("/roles/manage-users"):
                return 200, {"id": "role-uuid", "name": "manage-users"}
            self.fail(f"Unexpected request: {method} {path}")

        client = RecordingAdminClient(self.identity, handler)
        action = ensure_service_account_roles(client, "backend-uuid")

        self.assertEqual(action, "updated")
        posts = [
            body
            for method, _, body, _ in client.requests
            if method == "POST"
        ]
        self.assertEqual(
            posts,
            [[{"id": "role-uuid", "name": "manage-users"}]],
        )

    def test_undeclared_service_account_role_fails_closed(self) -> None:
        """Reject a broader role mapping instead of silently deleting it.

        Returns:
            Nothing.
        """

        def handler(method, path, body, query, expected):
            """Return one unexpected realm-management role."""

            if path.endswith("/service-account-user"):
                return 200, {"id": "service-user"}
            if query == {"clientId": "realm-management"}:
                return 200, [
                    {
                        "id": "realm-management-uuid",
                        "clientId": "realm-management",
                    }
                ]
            if path.endswith("/role-mappings/clients/realm-management-uuid"):
                return 200, [{"id": "admin", "name": "realm-admin"}]
            self.fail(f"Unexpected request: {method} {path}")

        client = RecordingAdminClient(self.identity, handler)
        with self.assertRaisesRegex(KeycloakRoleError, "undeclared roles"):
            ensure_service_account_roles(client, "backend-uuid")

    def test_regeneration_uses_keycloak_rotation_endpoint(self) -> None:
        """Return a rotated secret from POST without placing it in a URL.

        Returns:
            Nothing.
        """

        def handler(method, path, body, query, expected):
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

    def test_explicit_rotation_regenerates_then_replaces_docker_secret(
        self,
    ) -> None:
        """Bind a newly rotated Keycloak value to the exact Docker secret.

        Returns:
            Nothing.
        """

        with (
            patch(
                "keycloak_profile_bootstrap.stack_is_running",
                return_value=False,
            ),
            patch(
                "keycloak_profile_bootstrap.docker_secret_exists",
                return_value=True,
            ),
            patch("keycloak_profile_bootstrap.KeycloakAdminClient") as client_type,
            patch(
                "keycloak_profile_bootstrap.ensure_realm",
                return_value="kept",
            ),
            patch(
                "keycloak_profile_bootstrap._resolve_client_uuid",
                return_value="backend-uuid",
            ),
            patch(
                "keycloak_profile_bootstrap.ensure_client",
                side_effect=[
                    ("frontend-uuid", "kept"),
                    ("backend-uuid", "kept"),
                ],
            ),
            patch(
                "keycloak_profile_bootstrap.ensure_audience_mapper",
                return_value="kept",
            ),
            patch(
                "keycloak_profile_bootstrap.ensure_service_account_roles",
                return_value="kept",
            ),
            patch(
                "keycloak_profile_bootstrap.get_client_secret",
            ) as current_secret,
            patch(
                "keycloak_profile_bootstrap.regenerate_client_secret",
                return_value="new-sensitive-value",
            ) as rotate_secret,
            patch(
                "keycloak_profile_bootstrap.write_docker_secret",
                return_value="replaced",
            ) as write_secret,
        ):
            client_type.return_value = Mock(identity=self.identity)
            summary = reconcile(
                self.profile,
                "admin",
                "admin-password",
                replace_secret=True,
            )

        current_secret.assert_not_called()
        rotate_secret.assert_called_once()
        write_secret.assert_called_once_with(
            self.profile,
            self.identity,
            "new-sensitive-value",
            replace=True,
        )
        self.assertEqual(summary["dockerSecretAction"], "replaced")
        self.assertNotIn("new-sensitive-value", json.dumps(summary))

    @patch("keycloak_profile_bootstrap.write_docker_secret")
    @patch("keycloak_profile_bootstrap.regenerate_client_secret")
    @patch("keycloak_profile_bootstrap.get_client_secret")
    @patch("keycloak_profile_bootstrap.ensure_service_account_roles")
    @patch("keycloak_profile_bootstrap.ensure_audience_mapper")
    @patch("keycloak_profile_bootstrap.ensure_client")
    @patch("keycloak_profile_bootstrap._resolve_client_uuid")
    @patch("keycloak_profile_bootstrap.ensure_realm")
    @patch("keycloak_profile_bootstrap.KeycloakAdminClient")
    @patch("keycloak_profile_bootstrap.docker_secret_exists")
    def test_existing_docker_secret_is_not_read_or_replaced(
        self,
        secret_exists: Mock,
        client_type: Mock,
        ensure_realm_mock: Mock,
        resolve_uuid: Mock,
        ensure_client_mock: Mock,
        mapper_mock: Mock,
        roles_mock: Mock,
        get_secret_mock: Mock,
        rotate_secret_mock: Mock,
        write_secret_mock: Mock,
    ) -> None:
        """Keep a bound Docker secret without retrieving secret material.

        Args:
            secret_exists: Docker existence mock.
            client_type: Admin client constructor mock.
            ensure_realm_mock: Realm reconciliation mock.
            resolve_uuid: Backend lookup mock.
            ensure_client_mock: Client reconciliation mock.
            mapper_mock: Audience mapper mock.
            roles_mock: Service-account role mock.
            get_secret_mock: Current-secret retrieval mock.
            rotate_secret_mock: Rotation mock.
            write_secret_mock: Docker write mock.

        Returns:
            Nothing.
        """

        secret_exists.return_value = True
        client_type.return_value = Mock(identity=self.identity)
        ensure_realm_mock.return_value = "kept"
        resolve_uuid.return_value = "backend-uuid"
        ensure_client_mock.side_effect = [
            ("frontend-uuid", "kept"),
            ("backend-uuid", "kept"),
        ]
        mapper_mock.return_value = "kept"
        roles_mock.return_value = "kept"

        summary = reconcile(
            self.profile,
            "admin",
            "admin-password",
            replace_secret=False,
        )

        self.assertEqual(summary["dockerSecretAction"], "kept")
        get_secret_mock.assert_not_called()
        rotate_secret_mock.assert_not_called()
        write_secret_mock.assert_not_called()
        self.assertNotIn("admin-password", json.dumps(summary))


if __name__ == "__main__":
    unittest.main()
