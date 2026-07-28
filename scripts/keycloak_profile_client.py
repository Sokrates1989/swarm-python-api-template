"""
Module: keycloak_profile_client.py

Description:
    Defines the profile-derived Keycloak identity and a small standard-library
    Admin REST client. It normalizes only public site-config values and keeps
    administrator credentials and bearer tokens in process memory.

Dependencies:
    - Python standard library.
    - scripts/executable_profile.py.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from executable_profile import ExecutableProfile


class KeycloakProfileError(RuntimeError):
    """Report a safe, operator-facing Keycloak reconciliation failure."""


@dataclass(frozen=True)
class KeycloakIdentity:
    """Normalized public Keycloak identity declared by one site profile.

    Attributes:
        server_url: Public Keycloak base URL.
        realm: Realm name.
        frontend_client_id: Public PKCE client identifier.
        backend_client_id: Confidential service client identifier.
        audience: Audience added to frontend access tokens.
        redirect_uris: Exact mobile and WebApp callback allowlist.
        web_origins: Exact browser origin allowlist.
        frontend_root_url: Public WebApp root URL.
        api_root_url: Public backend root URL.
        docker_secret: Docker secret receiving the backend client secret.
        service_account_client_roles: Exact client-role grants keyed by the
            role-owning Keycloak client ID.
    """

    server_url: str
    realm: str
    frontend_client_id: str
    backend_client_id: str
    audience: str
    redirect_uris: tuple[str, ...]
    web_origins: tuple[str, ...]
    frontend_root_url: str
    api_root_url: str
    docker_secret: str
    service_account_client_roles: tuple[tuple[str, tuple[str, ...]], ...]


class KeycloakAdminClient:
    """Small Keycloak Admin REST client using only Python's standard library.

    Attributes:
        identity: Public realm/client configuration.
        token: Short-lived admin bearer token retained only in process memory.
    """

    def __init__(
        self,
        identity: KeycloakIdentity,
        admin_user: str,
        admin_password: str,
    ) -> None:
        """Authenticate the client against Keycloak's master realm.

        Args:
            identity: Profile-derived Keycloak identity.
            admin_user: Existing Keycloak administrator username.
            admin_password: Administrator password read without terminal echo.

        Raises:
            KeycloakProfileError: If authentication or token response fails.
        """

        self.identity = identity
        self.token = self._request_admin_token(admin_user, admin_password)

    def _request_admin_token(self, username: str, password: str) -> str:
        """Request a short-lived admin access token.

        Args:
            username: Keycloak administrator username.
            password: Keycloak administrator password.

        Returns:
            Bearer access token.

        Raises:
            KeycloakProfileError: If authentication or response parsing fails.
        """

        body = urllib.parse.urlencode(
            {
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": username,
                "password": password,
            }
        ).encode("utf-8")
        url = (
            f"{self.identity.server_url}/realms/master/"
            "protocol/openid-connect/token"
        )
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        payload = self._send(request, "authenticate with Keycloak")
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise KeycloakProfileError(
                "Keycloak admin token response did not contain an access token."
            )
        return token

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Any | None = None,
        query: dict[str, str] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> tuple[int, Any]:
        """Send one authenticated Keycloak Admin API request.

        Args:
            method: HTTP method.
            path: Absolute Admin API path beginning with ``/``.
            body: Optional JSON-compatible request body.
            query: Optional URL query mapping.
            expected: Accepted HTTP status codes.

        Returns:
            HTTP status and decoded JSON, or ``None`` for an empty body.

        Raises:
            KeycloakProfileError: If transport, status, or JSON parsing fails.
        """

        url = f"{self.identity.server_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status = int(response.status)
                raw = response.read()
        except urllib.error.HTTPError as error:
            status = int(error.code)
            raw = error.read()
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise KeycloakProfileError(
                f"Unable to reach Keycloak while requesting {path}."
            ) from error
        if status not in expected:
            raise KeycloakProfileError(
                f"Keycloak request {method} {path} returned HTTP {status}."
            )
        if not raw:
            return status, None
        try:
            return status, json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise KeycloakProfileError(
                f"Keycloak request {method} {path} returned invalid JSON."
            ) from error

    @staticmethod
    def _send(
        request: urllib.request.Request,
        action: str,
    ) -> dict[str, Any]:
        """Send an unauthenticated JSON-producing request.

        Args:
            request: Prepared urllib request.
            action: Operator-facing action description.

        Returns:
            Decoded JSON object.

        Raises:
            KeycloakProfileError: If transport, status, or parsing fails.
        """

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            raise KeycloakProfileError(
                f"Keycloak refused to {action} (HTTP {error.code})."
            ) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise KeycloakProfileError(f"Unable to {action}.") from error
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise KeycloakProfileError(
                f"Keycloak returned invalid JSON while trying to {action}."
            ) from error
        if not isinstance(payload, dict):
            raise KeycloakProfileError(
                f"Keycloak returned an unexpected response while trying to {action}."
            )
        return payload


def _backend_secret_name(profile: ExecutableProfile) -> str:
    """Resolve the backend client Docker secret from declared mounts.

    Args:
        profile: Validated executable profile.

    Returns:
        Exact Docker secret name.

    Raises:
        KeycloakProfileError: If no unique matching mount exists.
    """

    accepted_keys = {
        "KEYCLOAK_ADMIN_CLIENT_SECRET_FILE",
        "KEYCLOAK_CLIENT_SECRET_FILE",
    }
    matches = [
        mount.name
        for mount in profile.secret_mounts
        if mount.env_key in accepted_keys
    ]
    if len(matches) != 1:
        raise KeycloakProfileError(
            "The site profile must declare exactly one Keycloak client "
            "secret mount."
        )
    return matches[0]


def load_keycloak_identity(profile: ExecutableProfile) -> KeycloakIdentity:
    """Normalize all realm/client values from the active site profile.

    Args:
        profile: Validated executable profile.

    Returns:
        Immutable Keycloak identity.

    Raises:
        KeycloakProfileError: If the profile does not use Keycloak or lacks a
            WebApp root and client-secret mount.
    """

    raw = profile.data.get("auth")
    if not isinstance(raw, dict) or raw.get("provider") != "keycloak":
        raise KeycloakProfileError(
            "The selected site profile does not declare auth.provider=keycloak."
        )
    frontend_root = profile.deployment.get("WEB_BASE_URL", "")
    if not frontend_root:
        origins = raw.get("webOrigins", [])
        if not isinstance(origins, list) or not origins:
            raise KeycloakProfileError(
                "The Keycloak profile requires WEB_BASE_URL or a web origin."
            )
        frontend_root = str(origins[0])
    role_groups = raw.get("serviceAccountClientRoles", {})
    if not isinstance(role_groups, dict):
        raise KeycloakProfileError(
            "Keycloak service-account roles must be a client-role mapping."
        )
    return KeycloakIdentity(
        server_url=str(raw["serverUrl"]).rstrip("/"),
        realm=str(raw["realm"]),
        frontend_client_id=str(raw["frontendClientId"]),
        backend_client_id=str(raw["adminClientId"]),
        audience=str(raw["audience"]),
        redirect_uris=tuple(str(value) for value in raw["redirectUris"]),
        web_origins=tuple(str(value) for value in raw["webOrigins"]),
        frontend_root_url=frontend_root.rstrip("/"),
        api_root_url=profile.deployment["API_BASE_URL"].rstrip("/"),
        docker_secret=_backend_secret_name(profile),
        service_account_client_roles=tuple(
            (
                str(client_id),
                tuple(str(role) for role in roles),
            )
            for client_id, roles in role_groups.items()
        ),
    )


def realm_path(identity: KeycloakIdentity, suffix: str = "") -> str:
    """Build an escaped Keycloak realm Admin API path.

    Args:
        identity: Active Keycloak identity.
        suffix: Optional path following the realm.

    Returns:
        Escaped Admin API path.
    """

    realm = urllib.parse.quote(identity.realm, safe="")
    return f"/admin/realms/{realm}{suffix}"


def resolve_client_uuid(
    client: KeycloakAdminClient,
    client_id: str,
) -> str | None:
    """Resolve one Keycloak client UUID by its public client ID.

    Args:
        client: Authenticated Keycloak client.
        client_id: Declared OIDC client ID.

    Returns:
        UUID when found, otherwise ``None``.

    Raises:
        KeycloakProfileError: If the response is ambiguous or invalid.
    """

    _, payload = client.request(
        "GET",
        realm_path(client.identity, "/clients"),
        query={"clientId": client_id},
    )
    if not isinstance(payload, list):
        raise KeycloakProfileError(
            "Keycloak client lookup returned invalid data."
        )
    matches = [
        item
        for item in payload
        if isinstance(item, dict) and item.get("clientId") == client_id
    ]
    if not matches:
        return None
    if len(matches) != 1 or not isinstance(matches[0].get("id"), str):
        raise KeycloakProfileError(
            f"Keycloak client lookup for {client_id!r} was ambiguous."
        )
    return str(matches[0]["id"])


__all__ = [
    "KeycloakAdminClient",
    "KeycloakIdentity",
    "KeycloakProfileError",
    "load_keycloak_identity",
    "realm_path",
    "resolve_client_uuid",
]
