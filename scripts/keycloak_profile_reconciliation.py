"""
Module: keycloak_profile_reconciliation.py

Description:
    Reconciles the profile-owned Keycloak realm, public PKCE client,
    confidential backend client, audience mapper, and client credential. It
    preserves unrelated client attributes and avoids writes when desired state
    already matches.

Dependencies:
    - Python standard library.
    - scripts/keycloak_profile_client.py.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

from keycloak_profile_client import (
    KeycloakAdminClient,
    KeycloakIdentity,
    KeycloakProfileError,
    realm_path,
    resolve_client_uuid,
)


def realm_payload(identity: KeycloakIdentity) -> dict[str, Any]:
    """Build the exact profile-owned realm representation.

    Args:
        identity: Profile-derived Keycloak identity.

    Returns:
        Realm representation containing only explicitly owned fields.
    """

    return {
        "realm": identity.realm,
        "displayName": identity.realm_display_name,
        **dict(identity.realm_settings),
    }


def ensure_realm(client: KeycloakAdminClient) -> str:
    """Create or update the profile-owned realm settings.

    Args:
        client: Authenticated Keycloak client.

    Returns:
        ``created``, ``updated``, or ``kept``.

    Raises:
        KeycloakProfileError: If realm lookup or creation fails.
    """

    identity = client.identity
    status, current = client.request(
        "GET",
        realm_path(identity),
        expected=(200, 404),
    )
    desired = realm_payload(identity)
    if status == 200 and not isinstance(current, dict):
        raise KeycloakProfileError(
            "Keycloak realm lookup returned invalid data."
        )
    if status == 200 and _owned_fields_match(current, desired):
        return "kept"
    if status == 200:
        merged = dict(current)
        merged.update(desired)
        client.request(
            "PUT",
            realm_path(identity),
            body=merged,
            expected=(200, 204),
        )
        return "updated"
    client.request(
        "POST",
        "/admin/realms",
        body=desired,
        expected=(201, 204),
    )
    return "created"


def _post_logout_redirect_uris(identity: KeycloakIdentity) -> str:
    """Build Keycloak's exact post-logout redirect allowlist.

    Args:
        identity: Profile-derived Keycloak identity.

    Returns:
        Keycloak's ``##``-separated allowlist containing every declared
        application callback and each declared Web origin wildcard.
    """

    candidates = [
        *identity.redirect_uris,
        *(
            f"{origin.rstrip('/')}/*"
            for origin in identity.web_origins
        ),
    ]
    return "##".join(dict.fromkeys(candidates))


def frontend_payload(identity: KeycloakIdentity) -> dict[str, Any]:
    """Build the shared public PKCE client representation.

    Args:
        identity: Profile-derived Keycloak identity.

    Returns:
        Keycloak client representation.
    """

    return {
        "clientId": identity.frontend_client_id,
        "name": identity.frontend_client_id,
        "protocol": "openid-connect",
        "enabled": True,
        "publicClient": True,
        "standardFlowEnabled": True,
        "directAccessGrantsEnabled": False,
        "implicitFlowEnabled": False,
        "serviceAccountsEnabled": False,
        "authorizationServicesEnabled": False,
        "bearerOnly": False,
        "fullScopeAllowed": False,
        "rootUrl": identity.frontend_root_url,
        "baseUrl": "/",
        "redirectUris": list(identity.redirect_uris),
        "webOrigins": list(identity.web_origins),
        "attributes": {
            "pkce.code.challenge.method": "S256",
            "post.logout.redirect.uris": _post_logout_redirect_uris(identity),
        },
    }


def backend_payload(identity: KeycloakIdentity) -> dict[str, Any]:
    """Build the shared confidential service client representation.

    Args:
        identity: Profile-derived Keycloak identity.

    Returns:
        Keycloak client representation.
    """

    return {
        "clientId": identity.backend_client_id,
        "name": identity.backend_client_id,
        "protocol": "openid-connect",
        "enabled": True,
        "clientAuthenticatorType": "client-secret",
        "publicClient": False,
        "standardFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "implicitFlowEnabled": False,
        "serviceAccountsEnabled": True,
        "authorizationServicesEnabled": False,
        "bearerOnly": False,
        "fullScopeAllowed": False,
        "rootUrl": identity.api_root_url,
        "baseUrl": "/",
        "redirectUris": [],
        "webOrigins": [],
    }


def _owned_fields_match(
    current: dict[str, Any],
    desired: dict[str, Any],
) -> bool:
    """Compare only fields owned by the executable site profile.

    Args:
        current: Existing Keycloak representation.
        desired: Profile-owned fields.

    Returns:
        Whether every desired field already has the requested value.
    """

    for key, value in desired.items():
        if key == "attributes" and isinstance(value, dict):
            current_attributes = current.get("attributes")
            if not isinstance(current_attributes, dict):
                return False
            if any(
                current_attributes.get(name) != item
                for name, item in value.items()
            ):
                return False
        elif value is False and current.get(key) is None:
            continue
        elif value in ("", []) and current.get(key) is None:
            continue
        elif isinstance(value, list):
            current_value = current.get(key)
            current_list = (
                current_value if isinstance(current_value, list) else []
            )
            if sorted(current_list) != sorted(value):
                return False
        elif not isinstance(value, list) and current.get(key) != value:
            return False
    return True


def owned_fields_match(
    current: dict[str, Any],
    desired: dict[str, Any],
) -> bool:
    """Expose profile-owned representation comparison to verification.

    Args:
        current: Existing Keycloak representation.
        desired: Profile-owned desired fields.

    Returns:
        Whether every desired field is represented by current state.
    """

    return _owned_fields_match(current, desired)


def ensure_client(
    client: KeycloakAdminClient,
    payload: dict[str, Any],
) -> tuple[str, str]:
    """Create or idempotently update exactly one declared client.

    Args:
        client: Authenticated Keycloak client.
        payload: Profile-owned client fields.

    Returns:
        Client UUID and ``created``, ``updated``, or ``kept``.

    Raises:
        KeycloakProfileError: If lookup, creation, or update fails.
    """

    identity = client.identity
    client_id = str(payload["clientId"])
    client_uuid = resolve_client_uuid(client, client_id)
    clients_path = realm_path(identity, "/clients")
    if client_uuid is None:
        client.request(
            "POST",
            clients_path,
            body=payload,
            expected=(201, 204),
        )
        resolved = resolve_client_uuid(client, client_id)
        if resolved is None:
            raise KeycloakProfileError(
                f"Unable to resolve client {client_id!r} after creation."
            )
        return resolved, "created"
    escaped_uuid = urllib.parse.quote(client_uuid, safe="")
    _, current = client.request(
        "GET",
        f"{clients_path}/{escaped_uuid}",
    )
    if not isinstance(current, dict):
        raise KeycloakProfileError(
            f"Keycloak client {client_id!r} returned invalid data."
        )
    if _owned_fields_match(current, payload):
        return client_uuid, "kept"
    merged = dict(current)
    merged.update(payload)
    if isinstance(payload.get("attributes"), dict):
        attributes = current.get("attributes")
        merged_attributes = (
            dict(attributes) if isinstance(attributes, dict) else {}
        )
        merged_attributes.update(payload["attributes"])
        merged["attributes"] = merged_attributes
    client.request(
        "PUT",
        f"{clients_path}/{escaped_uuid}",
        body=merged,
        expected=(200, 204),
    )
    return client_uuid, "updated"


def audience_mapper_payload(
    identity: KeycloakIdentity,
) -> dict[str, Any]:
    """Build the exact frontend audience-mapper representation.

    Args:
        identity: Profile-derived Keycloak identity.

    Returns:
        Keycloak protocol-mapper representation.
    """

    return {
        "name": identity.audience_mapper_name,
        "protocol": "openid-connect",
        "protocolMapper": "oidc-audience-mapper",
        "consentRequired": False,
        "config": {
            "included.client.audience": identity.audience,
            "access.token.claim": "true",
            "id.token.claim": "false",
            "userinfo.token.claim": "false",
            "introspection.token.claim": "true",
        },
    }


def ensure_audience_mapper(
    client: KeycloakAdminClient,
    frontend_uuid: str,
) -> str:
    """Create or idempotently update the frontend audience mapper.

    Args:
        client: Authenticated Keycloak client.
        frontend_uuid: Public frontend client UUID.

    Returns:
        ``created``, ``updated``, or ``kept``.

    Raises:
        KeycloakProfileError: If mapper reconciliation fails.
    """

    identity = client.identity
    escaped_uuid = urllib.parse.quote(frontend_uuid, safe="")
    path = realm_path(
        identity,
        f"/clients/{escaped_uuid}/protocol-mappers/models",
    )
    _, current = client.request("GET", path)
    if not isinstance(current, list):
        raise KeycloakProfileError(
            "Keycloak protocol mapper lookup was invalid."
        )
    desired = audience_mapper_payload(identity)
    matches = [
        item
        for item in current
        if isinstance(item, dict) and item.get("name") == desired["name"]
    ]
    if not matches:
        client.request("POST", path, body=desired, expected=(201, 204))
        return "created"
    mapper_id = matches[0].get("id")
    if len(matches) != 1 or not isinstance(mapper_id, str):
        raise KeycloakProfileError("Backend audience mapper is ambiguous.")
    if _owned_fields_match(matches[0], desired):
        return "kept"
    desired["id"] = mapper_id
    client.request(
        "PUT",
        f"{path}/{urllib.parse.quote(mapper_id, safe='')}",
        body=desired,
        expected=(200, 204),
    )
    return "updated"


def _client_secret(
    client: KeycloakAdminClient,
    backend_uuid: str,
    *,
    rotate: bool,
) -> str:
    """Read or rotate one confidential client secret in process memory.

    Args:
        client: Authenticated Keycloak client.
        backend_uuid: Confidential backend client UUID.
        rotate: Use Keycloak's rotation endpoint when true.

    Returns:
        Current or newly generated secret.

    Raises:
        KeycloakProfileError: If Keycloak omits the credential.
    """

    escaped_uuid = urllib.parse.quote(backend_uuid, safe="")
    method = "POST" if rotate else "GET"
    _, payload = client.request(
        method,
        realm_path(
            client.identity,
            f"/clients/{escaped_uuid}/client-secret",
        ),
        expected=(200, 201) if rotate else (200,),
    )
    if not isinstance(payload, dict) or not isinstance(
        payload.get("value"),
        str,
    ):
        qualifier = "rotated " if rotate else ""
        raise KeycloakProfileError(
            f"Keycloak did not return the {qualifier}confidential client secret."
        )
    secret = str(payload["value"])
    if not secret:
        raise KeycloakProfileError(
            "Keycloak returned an empty confidential client secret."
        )
    return secret


def get_client_secret(
    client: KeycloakAdminClient,
    backend_uuid: str,
) -> str:
    """Fetch the current confidential backend client secret.

    Args:
        client: Authenticated Keycloak client.
        backend_uuid: Confidential backend client UUID.

    Returns:
        Current client secret retained only in memory.
    """

    return _client_secret(client, backend_uuid, rotate=False)


def regenerate_client_secret(
    client: KeycloakAdminClient,
    backend_uuid: str,
) -> str:
    """Rotate and return the confidential backend client secret.

    Args:
        client: Authenticated Keycloak client.
        backend_uuid: Confidential backend client UUID.

    Returns:
        Newly generated client secret retained only in memory.
    """

    return _client_secret(client, backend_uuid, rotate=True)


__all__ = [
    "audience_mapper_payload",
    "backend_payload",
    "ensure_audience_mapper",
    "ensure_client",
    "ensure_realm",
    "frontend_payload",
    "get_client_secret",
    "owned_fields_match",
    "realm_payload",
    "regenerate_client_secret",
]
