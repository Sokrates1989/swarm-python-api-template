"""
Module: keycloak_profile_client.py

Description:
    Defines the profile-derived Keycloak identity and a small standard-library
    Admin/OIDC client. It normalizes only public site-config values and keeps
    administrator credentials, client credentials, and bearer tokens in
    process memory. Optional tracing exposes only safe request metadata.

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
from executable_profile_support import mapping


class KeycloakProfileError(RuntimeError):
    """Report a safe, operator-facing Keycloak reconciliation failure."""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so credentials never leave the declared Keycloak URL."""

    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> None:
        """Decline every redirect.

        Args:
            request: Original urllib request.
            file_pointer: Response stream supplied by urllib.
            code: HTTP redirect status.
            message: HTTP status text.
            headers: Redirect response headers.
            new_url: Proposed redirect target.

        Returns:
            Always ``None``, which makes urllib surface the redirect status.
        """

        return None


def _read_http(
    request: urllib.request.Request,
) -> tuple[int, bytes]:
    """Send one request without redirects and return status plus raw body.

    Args:
        request: Prepared urllib request.

    Returns:
        HTTP status and response bytes, including HTTP error responses.

    Raises:
        KeycloakProfileError: If Keycloak cannot be reached.
    """

    opener = urllib.request.build_opener(_NoRedirectHandler())
    try:
        with opener.open(request, timeout=30) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as error:
        return int(error.code), error.read()
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise KeycloakProfileError("Unable to reach Keycloak.") from error


@dataclass(frozen=True)
class KeycloakIdentity:
    """Normalized public Keycloak identity declared by one site profile.

    Attributes:
        server_url: Public Keycloak base URL.
        issuer_url: Exact public issuer URL for the selected realm.
        jwks_url: Exact public JSON Web Key Set URL.
        realm: Realm name.
        realm_display_name: Human-readable realm name.
        realm_settings: Exact profile-owned realm boolean settings.
        frontend_client_id: Public PKCE client identifier.
        backend_client_id: Confidential service client identifier.
        audience: Audience added to frontend access tokens.
        audience_mapper_name: Exact frontend audience-mapper name.
        redirect_uris: Exact mobile and WebApp callback allowlist.
        web_origins: Exact browser origin allowlist.
        forbidden_default_usernames: Usernames that block automatic apply.
        frontend_root_url: Public WebApp root URL.
        api_root_url: Public backend root URL.
        docker_secret: Docker secret receiving the backend client secret.
        service_account_client_roles: Exact client-role grants keyed by the
            role-owning Keycloak client ID.
    """

    server_url: str
    issuer_url: str
    jwks_url: str
    realm: str
    realm_display_name: str
    realm_settings: tuple[tuple[str, bool], ...]
    frontend_client_id: str
    backend_client_id: str
    audience: str
    audience_mapper_name: str
    redirect_uris: tuple[str, ...]
    web_origins: tuple[str, ...]
    forbidden_default_usernames: tuple[str, ...]
    frontend_root_url: str
    api_root_url: str
    docker_secret: str
    service_account_client_roles: tuple[tuple[str, tuple[str, ...]], ...]


class KeycloakAdminClient:
    """Small Keycloak Admin REST client using only Python's standard library.

    Attributes:
        identity: Public realm/client configuration.
        token: Short-lived admin bearer token retained only in process memory.
        debug: Whether secret-safe request method/path/status tracing is active.
    """

    def __init__(
        self,
        identity: KeycloakIdentity,
        admin_user: str,
        admin_password: str,
        *,
        debug: bool = False,
    ) -> None:
        """Authenticate the client against Keycloak's master realm.

        Args:
            identity: Profile-derived Keycloak identity.
            admin_user: Existing Keycloak administrator username.
            admin_password: Administrator password read without terminal echo.
            debug: Emit request method, path, query-key names, and status only.
                Request bodies, headers, query values, and credentials are
                never included.

        Raises:
            KeycloakProfileError: If authentication or token response fails.
        """

        self.identity = identity
        self.debug = debug
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
        status, raw = _read_http(request)
        self._trace_response(method, path, query, status)
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

    def _trace_response(
        self,
        method: str,
        path: str,
        query: dict[str, str] | None,
        status: int,
    ) -> None:
        """Print one secret-safe Admin API response trace when enabled.

        Args:
            method: HTTP request method.
            path: Public Admin API path without server credentials.
            query: Optional query mapping; only key names are displayed.
            status: Observed HTTP status code.

        Returns:
            Nothing. Output is suppressed unless ``debug`` is true.
        """

        if not getattr(self, "debug", False):
            return
        query_note = ""
        if query:
            query_note = f" query-keys={','.join(sorted(query))}"
        print(
            f"[DEBUG] Keycloak Admin API {method} {path}"
            f"{query_note} -> HTTP {status}"
        )

    def public_json(self, url: str) -> dict[str, Any]:
        """Fetch one public Keycloak JSON document without admin credentials.

        Args:
            url: Exact profile-declared HTTPS URL.

        Returns:
            Decoded JSON object.

        Raises:
            KeycloakProfileError: If the URL leaves the configured Keycloak
                origin or the response is unavailable or malformed.
        """

        server = urllib.parse.urlparse(self.identity.server_url)
        target = urllib.parse.urlparse(url)
        if (
            target.scheme != server.scheme
            or target.netloc != server.netloc
            or target.username
            or target.password
        ):
            raise KeycloakProfileError(
                "Public Keycloak verification URL left the declared server."
            )
        request = urllib.request.Request(
            url,
            method="GET",
            headers={"Accept": "application/json"},
        )
        return self._send(request, "read public Keycloak metadata")

    def prove_client_credentials(
        self,
        client_id: str,
        client_secret: str,
    ) -> None:
        """Prove a confidential secret and declared user-read authority.

        Args:
            client_id: Exact confidential backend client ID.
            client_secret: Secret retained only in process memory.

        Returns:
            Nothing after Keycloak returns a token and, when the profile
            declares a compatible realm-management role, that token can read
            the selected realm's user administration endpoint.

        Raises:
            KeycloakProfileError: If Keycloak rejects the credential or omits
                an access token, or if a declared user-read role does not
                authorize the expected endpoint.
        """

        body = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.identity.issuer_url}/protocol/openid-connect/token",
            data=body,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        payload = self._send(
            request,
            "validate the backend client credential",
        )
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise KeycloakProfileError(
                "Keycloak client-credentials proof returned no access token."
            )
        if self._requires_user_access_proof():
            self._prove_user_admin_access(access_token)

    def _requires_user_access_proof(self) -> bool:
        """Check whether declared roles should authorize a realm-user read.

        Returns:
            Whether the profile declares a built-in realm-management role
            that grants user listing.
        """

        user_read_roles = {
            "manage-users",
            "view-users",
            "query-users",
        }
        return any(
            client_id == "realm-management"
            and bool(set(roles) & user_read_roles)
            for client_id, roles in self.identity.service_account_client_roles
        )

    def _prove_user_admin_access(self, access_token: str) -> None:
        """Require the service token to access the realm user endpoint.

        Args:
            access_token: Client-credentials token kept only in memory.

        Returns:
            Nothing after Keycloak returns a valid user list.

        Raises:
            KeycloakProfileError: If the token lacks the declared backend
                user-administration authority or the response is malformed.
        """

        realm = urllib.parse.quote(self.identity.realm, safe="")
        query = urllib.parse.urlencode({"max": "1"})
        request = urllib.request.Request(
            f"{self.identity.server_url}/admin/realms/{realm}/users?{query}",
            method="GET",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
        status, raw = _read_http(request)
        if status != 200:
            raise KeycloakProfileError(
                "The backend client credential was accepted, but its token "
                f"could not access realm users (HTTP {status})."
            )
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise KeycloakProfileError(
                "Keycloak returned invalid user-access proof data."
            ) from error
        if not isinstance(payload, list):
            raise KeycloakProfileError(
                "Keycloak returned unexpected user-access proof data."
            )

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

        status, raw = _read_http(request)
        if status != 200:
            raise KeycloakProfileError(
                f"Keycloak refused to {action} (HTTP {status})."
            )
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


def _frontend_roots(
    profile: ExecutableProfile,
    raw: dict[str, Any],
) -> tuple[str, str]:
    """Resolve configured and active WebApp roots.

    Args:
        profile: Validated executable profile.
        raw: Keycloak authentication mapping.

    Returns:
        Tracked configured root and active deployment root without trailing
        slashes.

    Raises:
        KeycloakProfileError: If neither deployment nor origin declares a
            usable WebApp root.
    """

    frontend_root = profile.deployment.get("WEB_BASE_URL", "")
    if not frontend_root:
        origins = raw.get("webOrigins", [])
        if not isinstance(origins, list) or not origins:
            raise KeycloakProfileError(
                "The Keycloak profile requires WEB_BASE_URL or a web origin."
            )
        frontend_root = str(origins[0])
    routing = mapping(profile.data.get("routing", {}), "routing")
    configured = str(routing.get("webBaseUrl", "")).rstrip("/")
    return configured, frontend_root.rstrip("/")


def _active_redirect_uris(
    raw: dict[str, Any],
    configured_root: str,
    deployment_root: str,
) -> tuple[str, ...]:
    """Map tracked WebApp callbacks to the active deployment root.

    Args:
        raw: Keycloak authentication mapping.
        configured_root: Tracked default WebApp root.
        deployment_root: Operator-selected active WebApp root.

    Returns:
        Exact active callback tuple, preserving custom-scheme callbacks.
    """

    return tuple(
        (
            f"{deployment_root}{str(value)[len(configured_root):]}"
            if configured_root
            and str(value).startswith(f"{configured_root}/")
            else str(value)
        )
        for value in raw["redirectUris"]
    )


def _active_web_origins(
    raw: dict[str, Any],
    configured_root: str,
    deployment_root: str,
) -> tuple[str, ...]:
    """Map the tracked WebApp origin to the active deployment origin.

    Args:
        raw: Keycloak authentication mapping.
        configured_root: Tracked default WebApp root.
        deployment_root: Operator-selected active WebApp root.

    Returns:
        Exact active browser-origin tuple.
    """

    return tuple(
        (
            deployment_root
            if str(value).rstrip("/") == configured_root
            else str(value)
        )
        for value in raw["webOrigins"]
    )


def _service_account_roles(
    raw: dict[str, Any],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Normalize exact service-account client-role groups.

    Args:
        raw: Keycloak authentication mapping.

    Returns:
        Immutable role groups in profile order.

    Raises:
        KeycloakProfileError: If role groups are not a JSON object.
    """

    role_groups = raw.get("serviceAccountClientRoles")
    if not isinstance(role_groups, dict):
        raise KeycloakProfileError(
            "Keycloak service-account roles must be a client-role mapping."
        )
    return tuple(
        (
            str(client_id),
            tuple(str(role) for role in roles),
        )
        for client_id, roles in role_groups.items()
    )


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
    configured_web_root, deployment_web_root = _frontend_roots(profile, raw)
    redirect_uris = _active_redirect_uris(
        raw,
        configured_web_root,
        deployment_web_root,
    )
    web_origins = _active_web_origins(
        raw,
        configured_web_root,
        deployment_web_root,
    )
    return KeycloakIdentity(
        server_url=str(raw["serverUrl"]).rstrip("/"),
        issuer_url=str(raw["issuerUrl"]).rstrip("/"),
        jwks_url=str(raw["jwksUrl"]).rstrip("/"),
        realm=str(raw["realm"]),
        realm_display_name=str(raw["realmDisplayName"]),
        realm_settings=tuple(
            (str(name), bool(value))
            for name, value in raw["realmSettings"].items()
        ),
        frontend_client_id=str(raw["frontendClientId"]),
        backend_client_id=str(raw["adminClientId"]),
        audience=str(raw["audience"]),
        audience_mapper_name=str(raw["audienceMapperName"]),
        redirect_uris=redirect_uris,
        web_origins=web_origins,
        forbidden_default_usernames=tuple(
            str(value) for value in raw["forbiddenDefaultUsernames"]
        ),
        frontend_root_url=deployment_web_root,
        api_root_url=profile.deployment["API_BASE_URL"].rstrip("/"),
        docker_secret=_backend_secret_name(profile),
        service_account_client_roles=_service_account_roles(raw),
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
