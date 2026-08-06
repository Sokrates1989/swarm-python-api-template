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

import json
import sys
import unittest
import urllib.parse
from contextlib import redirect_stdout
from io import StringIO
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
from keycloak_profile_admin_session import (  # noqa: E402
    AdminSessionManager,
    AdminTokenSession,
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
    client.debug = False
    return client


class KeycloakProfileClientTests(unittest.TestCase):
    """Exercise credential proof and public URL safety boundaries."""

    def test_debug_trace_excludes_bodies_headers_and_query_values(self) -> None:
        """Expose method/path/status evidence without credential material.

        Returns:
            Nothing.
        """

        client = client_fixture()
        client.debug = True
        output = StringIO()
        with patch(
            "keycloak_profile_client._read_http",
            return_value=(200, b"{}"),
        ), redirect_stdout(output):
            client.request(
                "POST",
                "/admin/realms/example/clients",
                body={"clientSecret": "hidden-body-value"},
                query={"clientId": "hidden-query-value"},
            )

        trace = output.getvalue()
        self.assertIn("POST /admin/realms/example/clients", trace)
        self.assertIn("query-keys=clientId", trace)
        self.assertIn("HTTP 200", trace)
        self.assertNotIn("hidden-body-value", trace)
        self.assertNotIn("hidden-query-value", trace)
        self.assertNotIn("unused-admin-token", trace)

    def test_expired_admin_token_refreshes_before_live_state_request(
        self,
    ) -> None:
        """Refresh a token expired during guided review before realm access.

        Returns:
            Nothing.
        """

        client = client_fixture()
        client.debug = True
        expired = AdminTokenSession(
            access_token="expired-access-token",
            refresh_token="hidden-refresh-token",
            access_expires_at=1,
            refresh_expires_at=0,
        )
        client._admin_session = AdminSessionManager(
            client.identity.server_url,
            expired,
            client._trace_admin_token_response,
        )
        client.token = expired.access_token
        refreshed_payload = json.dumps(
            {
                "access_token": "renewed-access-token",
                "refresh_token": "renewed-refresh-token",
                "expires_in": 300,
                "refresh_expires_in": 1800,
            }
        ).encode("utf-8")
        output = StringIO()
        with patch(
            "keycloak_profile_admin_session.read_keycloak_http",
            return_value=(200, refreshed_payload),
        ) as token_http, patch(
            "keycloak_profile_client._read_http",
            return_value=(200, b"{}"),
        ) as admin_http, redirect_stdout(output):
            status, payload = client.request(
                "GET",
                "/admin/realms/example",
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload, {})
        token_request = token_http.call_args.args[0]
        token_form = urllib.parse.parse_qs(
            token_request.data.decode("utf-8")
        )
        self.assertEqual(token_form["grant_type"], ["refresh_token"])
        self.assertEqual(
            token_form["refresh_token"],
            ["hidden-refresh-token"],
        )
        admin_request = admin_http.call_args.args[0]
        self.assertEqual(
            admin_request.get_header("Authorization"),
            "Bearer renewed-access-token",
        )
        trace = output.getvalue()
        self.assertIn("access token is expiring", trace)
        self.assertIn("Keycloak OIDC POST", trace)
        self.assertIn("HTTP 200", trace)
        self.assertNotIn("hidden-refresh-token", trace)
        self.assertNotIn("renewed-access-token", trace)

    def test_http_401_refreshes_and_retries_admin_request_once(self) -> None:
        """Recover from an unanticipated token rejection with one retry.

        Returns:
            Nothing.
        """

        client = client_fixture()
        active = AdminTokenSession.from_payload(
            {
                "access_token": "rejected-access-token",
                "refresh_token": "hidden-refresh-token",
                "expires_in": 3600,
                "refresh_expires_in": 7200,
            }
        )
        client._admin_session = AdminSessionManager(
            client.identity.server_url,
            active,
            client._trace_admin_token_response,
        )
        client.token = active.access_token
        refreshed_payload = json.dumps(
            {
                "access_token": "retry-access-token",
                "refresh_token": "retry-refresh-token",
                "expires_in": 300,
                "refresh_expires_in": 1800,
            }
        ).encode("utf-8")
        with patch(
            "keycloak_profile_admin_session.read_keycloak_http",
            return_value=(200, refreshed_payload),
        ), patch(
            "keycloak_profile_client._read_http",
            side_effect=[(401, b""), (200, b"{}")],
        ) as admin_http:
            status, payload = client.request(
                "GET",
                "/admin/realms/example",
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload, {})
        self.assertEqual(admin_http.call_count, 2)
        retry_request = admin_http.call_args_list[1].args[0]
        self.assertEqual(
            retry_request.get_header("Authorization"),
            "Bearer retry-access-token",
        )

    def test_http_401_without_refresh_token_explains_reauthentication(
        self,
    ) -> None:
        """Replace a generic 401 with an actionable expired-session message.

        Returns:
            Nothing.
        """

        client = client_fixture()
        session = AdminTokenSession.from_payload(
            {"access_token": "unrefreshable-token", "expires_in": 3600}
        )
        client._admin_session = AdminSessionManager(
            client.identity.server_url,
            session,
            client._trace_admin_token_response,
        )
        client.token = session.access_token
        with patch(
            "keycloak_profile_client._read_http",
            return_value=(401, b""),
        ), self.assertRaisesRegex(
            KeycloakProfileError,
            "Restart bootstrap and authenticate again",
        ):
            client.request("GET", "/admin/realms/example")

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
