"""
Module: keycloak_profile_realm_role_scope.py

Description:
    Reconciles the exact application realm roles required in the restricted
    public frontend client's dedicated scope. This keeps ``fullScopeAllowed``
    disabled while ensuring assigned application roles can reach access-token
    realm-role claims.

Dependencies:
    - Python standard library only.
    - Keycloak application-access models and a structural Admin client.
"""

from __future__ import annotations

import urllib.parse
from typing import Any, Protocol

from keycloak_profile_application_access import (
    KeycloakApplicationAccessError,
    KeycloakRealmRole,
)


class _Identity(Protocol):
    """Describe identity values required by frontend role scoping."""

    realm: str
    realm_roles: tuple[KeycloakRealmRole, ...]
    realm_role_catalog: tuple[KeycloakRealmRole, ...]


class _AdminClient(Protocol):
    """Describe the Keycloak Admin client used by this module."""

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


def _owned_role_catalog(identity: _Identity) -> tuple[KeycloakRealmRole, ...]:
    """Return every profile-owned role with a legacy-identity fallback.

    Args:
        identity: Active Keycloak identity.

    Returns:
        Full catalog, or the selected role set when no catalog is available.
    """

    catalog = getattr(identity, "realm_role_catalog", ())
    return catalog or identity.realm_roles


def _realm_path(identity: _Identity, suffix: str) -> str:
    """Build an escaped selected-realm Admin API path.

    Args:
        identity: Profile-derived Keycloak identity.
        suffix: Path following the realm root.

    Returns:
        Absolute Keycloak Admin API path.
    """

    realm = urllib.parse.quote(identity.realm, safe="")
    return f"/admin/realms/{realm}{suffix}"


def _scope_path(identity: _Identity, frontend_uuid: str) -> str:
    """Build the frontend client's direct realm-role scope path.

    Args:
        identity: Profile-derived Keycloak identity.
        frontend_uuid: Internal frontend client UUID.

    Returns:
        Exact Admin API scope-mapping path.
    """

    escaped = urllib.parse.quote(frontend_uuid, safe="")
    return _realm_path(identity, f"/clients/{escaped}/scope-mappings/realm")


def _read_scope_roles(
    client: _AdminClient,
    frontend_uuid: str,
) -> set[str]:
    """Read direct realm roles allowed by the frontend client scope.

    Args:
        client: Authenticated Keycloak Admin client.
        frontend_uuid: Internal frontend client UUID.

    Returns:
        Direct scoped realm-role names.

    Raises:
        KeycloakApplicationAccessError: If Keycloak returns malformed data.
    """

    _, payload = client.request(
        "GET",
        _scope_path(client.identity, frontend_uuid),
    )
    if not isinstance(payload, list) or any(
        not isinstance(role, dict) or not isinstance(role.get("name"), str)
        for role in payload
    ):
        raise KeycloakApplicationAccessError(
            "Keycloak frontend realm-role scope mapping was invalid."
        )
    return {str(role["name"]) for role in payload}


def inspect_frontend_realm_role_scope(
    client: _AdminClient,
    frontend_uuid: str | None,
) -> str:
    """Classify whether all declared application roles reach frontend tokens.

    Args:
        client: Authenticated Keycloak Admin client.
        frontend_uuid: Existing frontend UUID, or ``None`` when missing.

    Returns:
        ``none declared``, ``assign``, ``reconcile``, or ``keep``.
    """

    desired = {role.name for role in client.identity.realm_roles}
    owned = {role.name for role in _owned_role_catalog(client.identity)}
    if not desired and not owned:
        return "none declared"
    if frontend_uuid is None:
        return "assign" if desired else "none declared"
    assigned = _read_scope_roles(client, frontend_uuid)
    missing = desired - assigned
    obsolete = (assigned & owned) - desired
    if obsolete:
        return "reconcile"
    if missing:
        return "assign"
    return "keep" if desired else "none declared"


def _role_representations(
    client: _AdminClient,
    names: set[str],
) -> list[dict[str, Any]]:
    """Load complete declared role representations for a scope mutation.

    Args:
        client: Authenticated Keycloak Admin client.
        names: Missing role names.

    Returns:
        Role representations accepted by Keycloak.

    Raises:
        KeycloakApplicationAccessError: If a declared role is absent.
    """

    roles = {
        role.name: role for role in _owned_role_catalog(client.identity)
    }
    representations: list[dict[str, Any]] = []
    for name in sorted(names):
        escaped = urllib.parse.quote(name, safe="")
        status, payload = client.request(
            "GET",
            _realm_path(client.identity, f"/roles/{escaped}"),
            expected=(200, 404),
        )
        if status == 404 or not isinstance(payload, dict):
            raise KeycloakApplicationAccessError(
                f"Declared Keycloak realm role {roles[name].name!r} is missing."
            )
        representations.append(payload)
    return representations


def ensure_frontend_realm_role_scope(
    client: _AdminClient,
    frontend_uuid: str,
) -> str:
    """Add missing declared application roles to the frontend client scope.

    Args:
        client: Authenticated Keycloak Admin client.
        frontend_uuid: Internal frontend client UUID.

    Returns:
        ``none declared``, ``assigned``, ``reconciled``, or ``kept``.
    """

    desired = {role.name for role in client.identity.realm_roles}
    owned = {role.name for role in _owned_role_catalog(client.identity)}
    if not desired and not owned:
        return "none declared"
    assigned = _read_scope_roles(client, frontend_uuid)
    missing = desired - assigned
    obsolete = (assigned & owned) - desired
    path = _scope_path(client.identity, frontend_uuid)
    if missing:
        client.request(
            "POST",
            path,
            body=_role_representations(client, missing),
            expected=(204,),
        )
    if obsolete:
        client.request(
            "DELETE",
            path,
            body=_role_representations(client, obsolete),
            expected=(204,),
        )
    if obsolete:
        return "reconciled"
    if missing:
        return "assigned"
    return "kept" if desired else "none declared"


def verify_frontend_realm_role_scope(
    client: _AdminClient,
    frontend_uuid: str,
) -> None:
    """Require every declared application role in the frontend token scope.

    Args:
        client: Authenticated Keycloak Admin client.
        frontend_uuid: Internal frontend client UUID.

    Returns:
        Nothing when the mapping contains every declared role.

    Raises:
        KeycloakApplicationAccessError: If one or more roles remain missing.
    """

    desired = {role.name for role in client.identity.realm_roles}
    owned = {role.name for role in _owned_role_catalog(client.identity)}
    if not owned:
        return
    assigned = _read_scope_roles(client, frontend_uuid) & owned
    if assigned != desired:
        missing = desired - assigned
        obsolete = assigned - desired
        raise KeycloakApplicationAccessError(
            "Frontend client application-role scope remains drifted; missing="
            + ",".join(sorted(missing))
            + "; obsolete="
            + ",".join(sorted(obsolete))
        )


__all__ = [
    "ensure_frontend_realm_role_scope",
    "inspect_frontend_realm_role_scope",
    "verify_frontend_realm_role_scope",
]
