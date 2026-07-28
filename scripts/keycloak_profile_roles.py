"""
Module: keycloak_profile_roles.py

Description:
    Reconciles exact profile-declared client-role grants for a confidential
    Keycloak service account. Unexpected grants fail closed instead of being
    silently broadened, removed, or hidden.

Dependencies:
    - Python standard library only.
    - A structural Keycloak Admin client supplied by the caller.
"""

from __future__ import annotations

import urllib.parse
from typing import Any, Protocol


class KeycloakRoleError(RuntimeError):
    """Report invalid or unexpectedly broad service-account role state."""


class _Identity(Protocol):
    """Describe identity fields required by role reconciliation."""

    realm: str
    service_account_client_roles: tuple[tuple[str, tuple[str, ...]], ...]


class _AdminClient(Protocol):
    """Describe the Keycloak Admin client surface required by this module."""

    identity: _Identity

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | list[dict[str, Any]] | None = None,
        query: dict[str, str] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> tuple[int, Any]:
        """Send one authenticated Keycloak Admin API request."""


def _realm_path(identity: _Identity, suffix: str = "") -> str:
    """Build an escaped Keycloak realm Admin API path.

    Args:
        identity: Profile-derived Keycloak identity.
        suffix: Optional path following the realm.

    Returns:
        Escaped Admin API path.
    """

    realm = urllib.parse.quote(identity.realm, safe="")
    return f"/admin/realms/{realm}{suffix}"


def _resolve_client_uuid(
    client: _AdminClient,
    client_id: str,
) -> str:
    """Resolve exactly one Keycloak client UUID.

    Args:
        client: Authenticated Keycloak Admin client.
        client_id: Public ID of the role-owning client.

    Returns:
        Internal Keycloak client UUID.

    Raises:
        KeycloakRoleError: If the client is absent or ambiguous.
    """

    _, payload = client.request(
        "GET",
        _realm_path(client.identity, "/clients"),
        query={"clientId": client_id},
    )
    if not isinstance(payload, list):
        raise KeycloakRoleError("Keycloak client lookup returned invalid data.")
    matches = [
        item
        for item in payload
        if isinstance(item, dict) and item.get("clientId") == client_id
    ]
    if len(matches) != 1 or not isinstance(matches[0].get("id"), str):
        raise KeycloakRoleError(
            f"Role-owning Keycloak client {client_id!r} is missing or ambiguous."
        )
    return str(matches[0]["id"])


def _service_account_user_id(
    client: _AdminClient,
    backend_uuid: str,
) -> str:
    """Resolve the confidential client's service-account user UUID.

    Args:
        client: Authenticated Keycloak Admin client.
        backend_uuid: Confidential client UUID.

    Returns:
        Escaped service-account user UUID.

    Raises:
        KeycloakRoleError: If Keycloak omits the service account.
    """

    escaped_backend = urllib.parse.quote(backend_uuid, safe="")
    _, account = client.request(
        "GET",
        _realm_path(
            client.identity,
            f"/clients/{escaped_backend}/service-account-user",
        ),
    )
    if not isinstance(account, dict) or not isinstance(account.get("id"), str):
        raise KeycloakRoleError(
            "Keycloak backend service account could not be resolved."
        )
    return urllib.parse.quote(str(account["id"]), safe="")


def _load_assigned_role_names(
    client: _AdminClient,
    mapping_path: str,
) -> set[str]:
    """Load assigned role names from one role-owning client.

    Args:
        client: Authenticated Keycloak Admin client.
        mapping_path: Exact service-account role-mapping endpoint.

    Returns:
        Assigned role-name set.

    Raises:
        KeycloakRoleError: If Keycloak returns invalid mapping data.
    """

    _, assigned = client.request("GET", mapping_path)
    if not isinstance(assigned, list):
        raise KeycloakRoleError(
            "Keycloak service-account role mapping was invalid."
        )
    return {
        str(role["name"])
        for role in assigned
        if isinstance(role, dict) and isinstance(role.get("name"), str)
    }


def _load_role_representations(
    client: _AdminClient,
    roles_path: str,
    missing: list[str],
) -> list[dict[str, Any]]:
    """Load Keycloak representations for missing role names.

    Args:
        client: Authenticated Keycloak Admin client.
        roles_path: Role-owning client roles endpoint.
        missing: Missing desired role names.

    Returns:
        Role representations accepted by the mapping endpoint.

    Raises:
        KeycloakRoleError: If a declared role is absent or malformed.
    """

    representations: list[dict[str, Any]] = []
    for role_name in missing:
        _, role = client.request(
            "GET",
            f"{roles_path}/{urllib.parse.quote(role_name, safe='')}",
        )
        if not isinstance(role, dict):
            raise KeycloakRoleError(
                f"Keycloak role {role_name!r} returned invalid data."
            )
        representations.append(role)
    return representations


def _ensure_role_group(
    client: _AdminClient,
    user_uuid: str,
    role_client_id: str,
    desired_roles: tuple[str, ...],
) -> bool:
    """Reconcile one role-owning client's exact declared grants.

    Args:
        client: Authenticated Keycloak Admin client.
        user_uuid: Escaped service-account user UUID.
        role_client_id: Public ID of the role-owning client.
        desired_roles: Exact allowed roles for that client.

    Returns:
        Whether missing role grants were added.

    Raises:
        KeycloakRoleError: If existing grants exceed the declaration.
    """

    role_client_uuid = _resolve_client_uuid(client, role_client_id)
    escaped_role_client = urllib.parse.quote(role_client_uuid, safe="")
    mapping_path = _realm_path(
        client.identity,
        f"/users/{user_uuid}/role-mappings/clients/{escaped_role_client}",
    )
    assigned = _load_assigned_role_names(client, mapping_path)
    desired = set(desired_roles)
    unexpected = sorted(assigned - desired)
    if unexpected:
        raise KeycloakRoleError(
            "Backend service account has undeclared roles on "
            f"{role_client_id!r}: {', '.join(unexpected)}."
        )
    missing = sorted(desired - assigned)
    if not missing:
        return False
    roles_path = _realm_path(
        client.identity,
        f"/clients/{escaped_role_client}/roles",
    )
    client.request(
        "POST",
        mapping_path,
        body=_load_role_representations(client, roles_path, missing),
        expected=(204,),
    )
    return True


def ensure_service_account_roles(
    client: _AdminClient,
    backend_uuid: str,
) -> str:
    """Apply exact profile-declared roles to the backend service account.

    Args:
        client: Authenticated Keycloak Admin client.
        backend_uuid: Confidential backend client UUID.

    Returns:
        ``kept`` when no grant changed, otherwise ``updated``.

    Raises:
        KeycloakRoleError: If current or desired role state is invalid.
    """

    user_uuid = _service_account_user_id(client, backend_uuid)
    changed = False
    for role_client_id, desired_roles in (
        client.identity.service_account_client_roles
    ):
        if _ensure_role_group(
            client,
            user_uuid,
            role_client_id,
            desired_roles,
        ):
            changed = True
    return "updated" if changed else "kept"


__all__ = [
    "KeycloakRoleError",
    "ensure_service_account_roles",
]
