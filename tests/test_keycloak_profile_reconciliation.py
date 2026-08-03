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
from dataclasses import replace
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
    KeycloakProfileError,
    _frontend_payload,
    ensure_client,
    ensure_realm,
    load_keycloak_identity,
)
from keycloak_profile_reconciliation import (  # noqa: E402
    backend_payload,
    frontend_payload,
    owned_field_mismatches,
    realm_payload,
    test_smtp_connection,
)
from keycloak_profile_realm_configuration import (  # noqa: E402
    KeycloakEmailSenderSettings,
    KeycloakThemeSettings,
)
from keycloak_profile_theme_inventory import (  # noqa: E402
    load_available_themes,
)
from keycloak_profile_roles import (  # noqa: E402
    KeycloakRoleError,
    ensure_service_account_roles,
)
from keycloak_profile_verification import (  # noqa: E402
    _plan_blockers,
    _theme_availability_blockers,
    build_reconciliation_plan,
    verify_reconciled_state,
)
from tests.keycloak_profile_test_support import (  # noqa: E402
    RecordingAdminClient,
)


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
        # These tests isolate client, mapper, service-account, and protected
        # identity behavior. Application-role/test-user state has its own
        # stateful module and integration coverage.
        self.profile_data["auth"]["realmRoles"] = []
        self.profile_data["auth"]["bootstrapTestUsersEnabled"] = False
        self.profile_data["auth"]["bootstrapTestUsers"] = []
        self.profile_data["auth"]["forbiddenDefaultUsernames"] = ["test"]
        self.profile_data["auth"]["realmSettings"][
            "resetPasswordAllowed"
        ] = False
        self.profile_data["auth"]["realmSettings"]["verifyEmail"] = False
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

    def test_custom_theme_is_checked_against_live_server_inventory(self) -> None:
        """Block unavailable custom themes while accepting installed names.

        Returns:
            Nothing.
        """

        identity = replace(
            self.identity,
            theme_settings=KeycloakThemeSettings(
                "felix", "default", "default", "default"
            ),
        )

        def handler(method, path, body, query, expected):
            """Return a deterministic Keycloak theme inventory."""

            self.assertEqual((method, path), ("GET", "/admin/serverinfo"))
            return 200, {
                "themes": {
                    "login": [{"name": "keycloak"}, {"name": "felix"}],
                    "account": [{"name": "keycloak.v3"}],
                    "admin": [{"name": "keycloak.v2"}],
                    "email": [{"name": "keycloak"}],
                }
            }

        client = RecordingAdminClient(identity, handler)
        self.assertEqual(
            load_available_themes(client)["login"],
            ("felix", "keycloak"),
        )
        self.assertEqual(_theme_availability_blockers(client), [])
        unavailable = replace(
            identity,
            theme_settings=KeycloakThemeSettings(
                "missing", "default", "default", "default"
            ),
        )
        blockers = _theme_availability_blockers(
            RecordingAdminClient(unavailable, handler)
        )
        self.assertEqual(len(blockers), 1)
        self.assertIn("'missing' is unavailable", blockers[0])

    def test_email_dependent_realm_requires_managed_or_existing_smtp(
        self,
    ) -> None:
        """Block unsafe email settings unless a sender is configured.

        Returns:
            Nothing.
        """

        realm_settings = dict(self.identity.realm_settings)
        realm_settings["verifyEmail"] = True
        identity = replace(
            self.identity,
            realm_settings=tuple(realm_settings.items()),
        )
        client = Mock(identity=identity)
        arguments = {
            "realm_exists": False,
            "backend_action": "create",
            "unexpected_roles": (),
            "test_user_actions": {},
            "docker_secret_present": False,
            "replace_secret": False,
        }

        blockers = _plan_blockers(
            client,
            email_sender_present=False,
            **arguments,
        )
        self.assertEqual(len(blockers), 1)
        self.assertIn("Configure a realm email sender", blockers[0])
        self.assertEqual(
            _plan_blockers(
                client,
                email_sender_present=True,
                **arguments,
            ),
            [],
        )

    def test_existing_realm_drift_is_updated_with_owned_settings(self) -> None:
        """Update drifted realm fields while preserving unrelated state.

        Returns:
            Nothing.
        """

        desired = realm_payload(self.identity)
        current = {
            **desired,
            "rememberMe": False,
            "unrelatedSetting": "preserved",
        }
        updated_bodies: list[dict[str, Any]] = []

        def handler(method, path, body, query, expected):
            """Serve one drifted realm and record the correcting update."""

            self.assertIsNone(query)
            if method == "GET":
                return 200, current
            if method == "PUT":
                self.assertIsInstance(body, dict)
                updated_bodies.append(dict(body))
                current.update(body)
                return 204, None
            self.fail(f"Unexpected request: {method} {path}")

        client = RecordingAdminClient(self.identity, handler)
        action = ensure_realm(client)

        self.assertEqual(action, "updated")
        self.assertEqual(len(updated_bodies), 1)
        self.assertIs(updated_bodies[0]["rememberMe"], True)
        self.assertEqual(
            updated_bodies[0]["unrelatedSetting"],
            "preserved",
        )

    def test_ignored_realm_update_is_detected_by_strict_verification(
        self,
    ) -> None:
        """Fail when Keycloak accepts a realm update but retains drift.

        Returns:
            Nothing.
        """

        drifted = {
            **realm_payload(self.identity),
            "rememberMe": False,
        }

        def handler(method, path, body, query, expected):
            """Acknowledge realm updates without applying them."""

            self.assertIsNone(query)
            if method == "GET":
                return 200, drifted
            if method == "PUT":
                return 204, None
            self.fail(f"Unexpected request: {method} {path}")

        client = RecordingAdminClient(self.identity, handler)

        self.assertEqual(ensure_realm(client), "updated")
        with self.assertRaisesRegex(
            KeycloakProfileError,
            "realm verification found unresolved drift",
        ):
            verify_reconciled_state(client)

    def test_smtp_password_is_runtime_only_and_connection_is_tested(
        self,
    ) -> None:
        """Write and test SMTP with a password absent from desired evidence.

        Returns:
            Nothing.
        """

        sender = KeycloakEmailSenderSettings(
            True,
            "noreply@example.com",
            "Example",
            "",
            "",
            "",
            "smtp.example.com",
            587,
            True,
            False,
            True,
            "smtp-user",
        )
        identity = replace(self.identity, email_sender_settings=sender)
        desired = realm_payload(identity)
        self.assertNotIn("password", desired["smtpServer"])
        current = {
            **desired,
            "smtpServer": {**desired["smtpServer"], "host": "old.example.com"},
        }
        bodies: list[tuple[str, dict[str, Any]]] = []

        def handler(method, path, body, query, expected):
            """Record realm mutation and SMTP test request bodies."""

            self.assertIsNone(query)
            if method == "GET":
                return 200, current
            self.assertIsInstance(body, dict)
            bodies.append((path, dict(body)))
            if method == "PUT":
                current.update(body)
                return 204, None
            if method == "POST" and path.endswith("/testSMTPConnection"):
                return 204, None
            self.fail(f"Unexpected request: {method} {path}")

        client = RecordingAdminClient(identity, handler)
        self.assertEqual(
            ensure_realm(client, smtp_password="smtp-secret"),
            "updated",
        )
        self.assertEqual(
            test_smtp_connection(client, smtp_password="smtp-secret"),
            "passed",
        )
        self.assertEqual(bodies[0][1]["smtpServer"]["password"], "smtp-secret")
        self.assertEqual(bodies[1][1]["password"], "smtp-secret")

    def test_declared_role_is_added_to_assignment_and_scope(self) -> None:
        """Add the declared assignment and dedicated client-scope mapping.

        Returns:
            Nothing.
        """

        def handler(method, path, body, query, expected):
            """Return deterministic service-account and role fixtures."""

            if path.endswith("/service-account-user"):
                return 200, {"id": "service-user"}
            if path.endswith("/users/service-user/role-mappings"):
                return 200, {
                    "realmMappings": [
                        {"name": "default-roles-felix"},
                    ],
                    "clientMappings": {},
                }
            if path.endswith("/clients/backend-uuid/scope-mappings"):
                return 200, {
                    "realmMappings": [],
                    "clientMappings": {},
                }
            if query == {"clientId": "realm-management"}:
                return 200, [
                    {
                        "id": "realm-management-uuid",
                        "clientId": "realm-management",
                    }
                ]
            if "/evaluate-scopes/scope-mappings/" in path:
                return 200, []
            if path.endswith(
                (
                    "/role-mappings/clients/realm-management-uuid",
                    "/scope-mappings/clients/realm-management-uuid",
                )
            ):
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
            [
                [{"id": "role-uuid", "name": "manage-users"}],
                [{"id": "role-uuid", "name": "manage-users"}],
            ],
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
            if path.endswith("/users/service-user/role-mappings"):
                return 200, {
                    "realmMappings": [
                        {"name": "default-roles-felix"},
                    ],
                    "clientMappings": {
                        "realm-management": {
                            "client": "realm-management",
                            "mappings": [
                                {"id": "admin", "name": "realm-admin"},
                            ],
                        }
                    },
                }
            if path.endswith("/clients/backend-uuid/scope-mappings"):
                return 200, {}
            self.fail(f"Unexpected request: {method} {path}")

        client = RecordingAdminClient(self.identity, handler)
        with self.assertRaisesRegex(KeycloakRoleError, "undeclared roles"):
            ensure_service_account_roles(client, "backend-uuid")

    def test_complete_role_inventory_rejects_undeclared_grants(self) -> None:
        """Reject direct realm and undeclared-client grants before mutation.

        Returns:
            Nothing.
        """

        cases = (
            (
                "realm",
                {
                    "realmMappings": [{"name": "realm-admin"}],
                    "clientMappings": {},
                },
                {},
            ),
            (
                "other-client",
                {
                    "realmMappings": [],
                    "clientMappings": {
                        "account": {
                            "client": "account",
                            "mappings": [{"name": "manage-account"}],
                        }
                    },
                },
                {},
            ),
            (
                "client-scope",
                {
                    "realmMappings": [
                        {"name": "default-roles-felix"},
                    ],
                    "clientMappings": {},
                },
                {
                    "realmMappings": [],
                    "clientMappings": {
                        "account": {
                            "client": "account",
                            "mappings": [{"name": "manage-account"}],
                        }
                    },
                },
            ),
        )
        for label, assignment_inventory, scope_inventory in cases:
            with self.subTest(case=label):

                def handler(method, path, body, query, expected):
                    """Return one unsafe complete assignment inventory."""

                    if path.endswith("/service-account-user"):
                        return 200, {"id": "service-user"}
                    if path.endswith("/users/service-user/role-mappings"):
                        return 200, assignment_inventory
                    if path.endswith(
                        "/clients/backend-uuid/scope-mappings"
                    ):
                        return 200, scope_inventory
                    self.fail(f"Unexpected request: {method} {path}")

                client = RecordingAdminClient(self.identity, handler)
                with self.assertRaisesRegex(
                    KeycloakRoleError,
                    "undeclared roles",
                ):
                    ensure_service_account_roles(client, "backend-uuid")
                self.assertFalse(
                    any(
                        method == "POST"
                        for method, _, _, _ in client.requests
                    )
                )

    def test_effective_client_scope_rejects_hidden_broader_role(
        self,
    ) -> None:
        """Reject an extra effective role inherited through client scopes.

        Returns:
            Nothing.
        """

        declared_mapping = {
            "realmMappings": [],
            "clientMappings": {
                "realm-management": {
                    "client": "realm-management",
                    "mappings": [{"name": "manage-users"}],
                }
            },
        }

        def handler(method, path, body, query, expected):
            """Expose safe direct mappings but one unsafe effective role."""

            if path.endswith("/service-account-user"):
                return 200, {"id": "service-user"}
            if path.endswith("/users/service-user/role-mappings"):
                return 200, {
                    **declared_mapping,
                    "realmMappings": [
                        {"name": "default-roles-felix"},
                    ],
                }
            if path.endswith("/clients/backend-uuid/scope-mappings"):
                return 200, declared_mapping
            if query == {"clientId": "realm-management"}:
                return 200, [
                    {
                        "id": "realm-management-uuid",
                        "clientId": "realm-management",
                    }
                ]
            if "/evaluate-scopes/scope-mappings/" in path:
                return 200, [
                    {"name": "manage-users"},
                    {"name": "realm-admin"},
                ]
            self.fail(f"Unexpected request: {method} {path}")

        client = RecordingAdminClient(self.identity, handler)
        with self.assertRaisesRegex(KeycloakRoleError, "undeclared roles"):
            ensure_service_account_roles(client, "backend-uuid")
        self.assertFalse(
            any(method == "POST" for method, _, _, _ in client.requests)
        )

    def test_full_scope_legacy_client_can_migrate_before_effective_check(
        self,
    ) -> None:
        """Plan a safe full-scope disable before exact effective verification.

        Returns:
            Nothing.
        """

        frontend = ("frontend-uuid", frontend_payload(self.identity))
        backend_state = backend_payload(self.identity)
        backend_state["fullScopeAllowed"] = True
        backend = ("backend-uuid", backend_state)
        declared_mapping = {
            "realmMappings": [],
            "clientMappings": {
                "realm-management": {
                    "client": "realm-management",
                    "mappings": [{"name": "manage-users"}],
                }
            },
        }

        def handler(method, path, body, query, expected):
            """Serve exact direct roles and reject premature effective reads."""

            if path.endswith("/service-account-user"):
                return 200, {"id": "service-user"}
            if path.endswith("/users/service-user/role-mappings"):
                return 200, {
                    **declared_mapping,
                    "realmMappings": [
                        {"name": "default-roles-felix"},
                    ],
                }
            if path.endswith("/clients/backend-uuid/scope-mappings"):
                return 200, declared_mapping
            if "/evaluate-scopes/" in path:
                self.fail(
                    "Effective scope must wait until full scope is disabled."
                )
            self.fail(f"Unexpected request: {method} {path}")

        client = RecordingAdminClient(self.identity, handler)
        with (
            patch(
                "keycloak_profile_verification._read_realm",
                return_value=realm_payload(self.identity),
            ),
            patch(
                "keycloak_profile_verification._read_client",
                side_effect=[frontend, backend],
            ),
            patch(
                "keycloak_profile_verification._read_mapper_action",
                return_value="keep",
            ),
            patch(
                "keycloak_profile_verification.find_forbidden_users",
                return_value=(),
            ),
        ):
            plan = build_reconciliation_plan(
                client,
                docker_secret_present=True,
                replace_secret=False,
            )

        self.assertEqual(plan["backendClient"], "update")
        self.assertEqual(plan["serviceAccountRoles"], "keep")
        self.assertEqual(plan["blockers"], [])

    def test_forbidden_default_user_blocks_reconciliation_plan(self) -> None:
        """Expose a present ``test`` user as an explicit apply blocker.

        Returns:
            Nothing.
        """

        frontend = ("frontend-uuid", frontend_payload(self.identity))
        backend = ("backend-uuid", backend_payload(self.identity))
        client = Mock(identity=self.identity)
        with (
            patch(
                "keycloak_profile_verification._read_realm",
                return_value=realm_payload(self.identity),
            ),
            patch(
                "keycloak_profile_verification._read_client",
                side_effect=[frontend, backend],
            ),
            patch(
                "keycloak_profile_verification._read_mapper_action",
                return_value="keep",
            ),
            patch(
                "keycloak_profile_verification._role_plan",
                return_value=("keep", ()),
            ),
            patch(
                "keycloak_profile_verification.find_forbidden_users",
                return_value=("test",),
            ),
        ):
            plan = build_reconciliation_plan(
                client,
                docker_secret_present=False,
                replace_secret=False,
            )

        self.assertEqual(
            plan["blockers"],
            ["Delete forbidden default user explicitly: test"],
        )
        self.assertEqual(plan["dockerSecret"], "fetch-prove-and-create")

    def _assert_public_metadata_rejected(
        self,
        discovery: dict[str, Any],
        jwks: dict[str, Any],
        message: str,
    ) -> None:
        """Assert that invalid public OIDC evidence fails verification.

        Args:
            discovery: Public discovery response.
            jwks: Public signing-key response.
            message: Expected safe error fragment.

        Returns:
            Nothing.
        """

        client = Mock(identity=self.identity)
        client.public_json.side_effect = [discovery, jwks]
        with (
            patch(
                "keycloak_profile_verification._read_realm",
                return_value=realm_payload(self.identity),
            ),
            patch(
                "keycloak_profile_verification._read_client",
                side_effect=[
                    (
                        "frontend-uuid",
                        frontend_payload(self.identity),
                    ),
                    (
                        "backend-uuid",
                        backend_payload(self.identity),
                    ),
                ],
            ),
            patch("keycloak_profile_verification._verify_mapper"),
            patch(
                "keycloak_profile_verification."
                "verify_service_account_roles",
            ),
            patch(
                "keycloak_profile_verification.find_forbidden_users",
                return_value=(),
            ),
        ):
            with self.assertRaisesRegex(KeycloakProfileError, message):
                verify_reconciled_state(client)

    def test_discovery_issuer_and_jwks_fail_closed(self) -> None:
        """Reject a mismatched issuer and an empty public signing-key set.

        Returns:
            Nothing.
        """

        cases = (
            (
                "issuer",
                {"issuer": "https://keycloak.fe-wi.com/realms/wrong"},
                {"keys": [{"kid": "key-1"}]},
                "discovery issuer",
            ),
            (
                "jwks",
                {"issuer": self.identity.issuer_url},
                {"keys": []},
                "JWKS verification returned no signing keys",
            ),
        )
        for label, discovery, jwks, message in cases:
            with self.subTest(case=label):
                self._assert_public_metadata_rejected(
                    discovery,
                    jwks,
                    message,
                )

    def test_backend_ignores_keycloak_derived_browser_fields(self) -> None:
        """Accept Keycloak 26 redirect/origin defaults on service clients.

        Returns:
            Nothing.
        """

        desired = backend_payload(self.identity)
        current = {
            **desired,
            "redirectUris": [f"{self.identity.api_root_url}/*"],
            "webOrigins": [self.identity.api_root_url],
        }

        self.assertNotIn("redirectUris", desired)
        self.assertNotIn("webOrigins", desired)
        self.assertEqual(owned_field_mismatches(current, desired), ())


if __name__ == "__main__":
    unittest.main()
