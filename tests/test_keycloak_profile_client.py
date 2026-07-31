"""
Module: test_keycloak_profile_client.py

Description:
    Verifies secret-safe OIDC client-credentials proof and public metadata
    origin enforcement in the generic Keycloak HTTP client.

Dependencies:
    - Python standard library.
    - scripts/keycloak_profile_client.py.
"""

from __future__ import annotations

import sys
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIRECTORY = REPOSITORY_ROOT / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

from keycloak_profile_client import (  # noqa: E402
    KeycloakAdminClient,
    KeycloakIdentity,
    KeycloakProfileError,
)


def identity_fixture() -> KeycloakIdentity:
    """Build one generic secret-free Keycloak identity fixture.

    Returns:
        Complete immutable identity used by HTTP client tests.
    """

    return KeycloakIdentity(
        server_url="https://keycloak.example.com",
        issuer_url="https://keycloak.example.com/realms/example",
        jwks_url=(
            "https://keycloak.example.com/realms/example/"
            "protocol/openid-connect/certs"
        ),
        realm="example",
        realm_display_name="Example",
        realm_settings=(("enabled", True),),
        frontend_client_id="example-frontend",
        backend_client_id="example-backend",
        audience="example-backend",
        audience_mapper_name="backend-audience",
        redirect_uris=("example:/callback",),
        web_origins=("https://app.example.com",),
        forbidden_default_usernames=("test",),
        frontend_root_url="https://app.example.com",
        api_root_url="https://api.example.com",
        docker_secret="EXAMPLE_KEYCLOAK_SECRET",
        service_account_client_roles=(
            ("realm-management", ("manage-users",)),
        ),
    )


def client_fixture() -> KeycloakAdminClient:
    """Build an authenticated-client shell without performing network I/O.

    Returns:
        Client with fixture identity and an unused placeholder admin token.
    """

    client = object.__new__(KeycloakAdminClient)
    client.identity = identity_fixture()
    client.token = "unused-admin-token"
    return client


class KeycloakProfileClientTests(unittest.TestCase):
    """Exercise credential proof and public URL safety boundaries."""

    def test_client_credentials_proof_posts_exact_secret_in_body(self) -> None:
        """Send the Keycloak-returned value only in the token request body.

        Returns:
            Nothing.
        """

        client = client_fixture()
        secret = "real-keycloak-secret"
        with patch.object(
            KeycloakAdminClient,
            "_send",
            return_value={"access_token": "proof-token"},
        ) as send, patch(
            "keycloak_profile_client._read_http",
            return_value=(200, b"[]"),
        ) as read_http:
            client.prove_client_credentials("example-backend", secret)

        request = send.call_args.args[0]
        parameters = urllib.parse.parse_qs(request.data.decode("utf-8"))
        self.assertEqual(parameters["client_secret"], [secret])
        self.assertEqual(parameters["client_id"], ["example-backend"])
        self.assertEqual(parameters["grant_type"], ["client_credentials"])
        self.assertNotIn(secret, request.full_url)
        access_request = read_http.call_args.args[0]
        self.assertEqual(
            access_request.get_header("Authorization"),
            "Bearer proof-token",
        )
        self.assertIn("/admin/realms/example/users?max=1", access_request.full_url)

    def test_client_credentials_proof_requires_user_admin_access(self) -> None:
        """Reject a valid token that lacks backend user-management authority.

        Returns:
            Nothing.
        """

        client = client_fixture()
        with (
            patch.object(
                KeycloakAdminClient,
                "_send",
                return_value={"access_token": "under-scoped-token"},
            ),
            patch(
                "keycloak_profile_client._read_http",
                return_value=(403, b""),
            ),
            self.assertRaisesRegex(
                KeycloakProfileError,
                "could not access realm users",
            ),
        ):
            client.prove_client_credentials(
                "example-backend",
                "accepted-but-under-scoped-secret",
            )

    def test_client_credentials_proof_requires_access_token(self) -> None:
        """Reject a nominal token response that proves no credential.

        Returns:
            Nothing.
        """

        client = client_fixture()
        with (
            patch.object(KeycloakAdminClient, "_send", return_value={}),
            self.assertRaisesRegex(
                KeycloakProfileError,
                "returned no access token",
            ),
        ):
            client.prove_client_credentials(
                "example-backend",
                "invalid-secret",
            )

    def test_client_credentials_without_user_roles_needs_only_token(
        self,
    ) -> None:
        """Keep credential proof generic when no user-read role is declared.

        Returns:
            Nothing.
        """

        client = client_fixture()
        client.identity = KeycloakIdentity(
            **{
                **client.identity.__dict__,
                "service_account_client_roles": (),
            }
        )
        with (
            patch.object(
                KeycloakAdminClient,
                "_send",
                return_value={"access_token": "proof-token"},
            ),
            patch(
                "keycloak_profile_client._read_http"
            ) as read_http,
        ):
            client.prove_client_credentials(
                "example-backend",
                "valid-secret",
            )

        read_http.assert_not_called()

    def test_public_metadata_must_stay_on_declared_origin(self) -> None:
        """Reject public verification URLs on another origin before I/O.

        Returns:
            Nothing.
        """

        client = client_fixture()
        with self.assertRaisesRegex(
            KeycloakProfileError,
            "left the declared server",
        ):
            client.public_json(
                "https://attacker.example/realms/example/metadata"
            )


if __name__ == "__main__":
    unittest.main()
