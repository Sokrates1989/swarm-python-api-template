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


def _role_names(raw: Any, context: str) -> set[str]:
    """Normalize one Keycloak role-representation list.

    Args:
        raw: Candidate list of role representations.
        context: Secret-free operator label used in errors.

    Returns:
        Exact represented role names.

    Raises:
        KeycloakRoleError: If any representation is malformed.
    """

    if raw is None:
        return set()
    if not isinstance(raw, list) or any(
        not isinstance(role, dict)
        or not isinstance(role.get("name"), str)
        for role in raw
    ):
        raise KeycloakRoleError(
            f"Keycloak {context} role inventory was invalid."
        )
    return {str(role["name"]) for role in raw}


def _load_mapping_inventory(
    client: _AdminClient,
    mapping_path: str,
    context: str,
) -> tuple[set[str], dict[str, set[str]]]:
    """Load all direct realm and client roles from one mapping owner.

    Args:
        client: Authenticated Keycloak Admin client.
        mapping_path: Complete role-mapping inventory endpoint.
        context: Secret-free operator label used in errors.

    Returns:
        Direct realm roles and direct client roles keyed by public client ID.

    Raises:
        KeycloakRoleError: If Keycloak returns malformed inventory data.
    """

    _, payload = client.request("GET", mapping_path)
    if not isinstance(payload, dict):
        raise KeycloakRoleError(
            f"Keycloak {context} role inventory was invalid."
        )
    raw_clients = payload.get("clientMappings", {})
    if raw_clients is None:
        raw_clients = {}
    if not isinstance(raw_clients, dict):
        raise KeycloakRoleError(
            f"Keycloak {context} client-role inventory was invalid."
        )
    client_roles: dict[str, set[str]] = {}
    for key, value in raw_clients.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            raise KeycloakRoleError(
                f"Keycloak {context} client-role inventory was invalid."
            )
        client_id = value.get("client", key)
        if not isinstance(client_id, str) or not client_id:
            raise KeycloakRoleError(
                f"Keycloak {context} client identity was invalid."
            )
        client_roles.setdefault(client_id, set()).update(
            _role_names(value.get("mappings"), context)
        )
    return (
        _role_names(payload.get("realmMappings"), context),
        client_roles,
    )


def _inventory_differences(
    inventory: tuple[set[str], dict[str, set[str]]],
    desired_clients: dict[str, set[str]],
    allowed_realm_roles: set[str],
    label: str,
) -> tuple[list[str], list[str]]:
    """Compare one complete direct-role inventory with profile policy.

    Args:
        inventory: Current direct realm and client role assignments.
        desired_clients: Exact desired roles keyed by role-owning client ID.
        allowed_realm_roles: Permitted direct realm roles.
        label: Mapping-owner label included in qualified results.

    Returns:
        Missing and unexpected qualified role names.
    """

    realm_roles, actual_clients = inventory
    missing: list[str] = []
    unexpected = [
        f"{label}:realm/{role}"
        for role in sorted(realm_roles - allowed_realm_roles)
    ]
    for client_id, desired_roles in desired_clients.items():
        actual = actual_clients.get(client_id, set())
        missing.extend(
            f"{label}:{client_id}/{role}"
            for role in sorted(desired_roles - actual)
        )
    for client_id, actual_roles in actual_clients.items():
        desired = desired_clients.get(client_id, set())
        unexpected.extend(
            f"{label}:{client_id}/{role}"
            for role in sorted(actual_roles - desired)
        )
    return missing, unexpected


def _effective_scope_differences(
    client: _AdminClient,
    backend_uuid: str,
    desired_clients: dict[str, set[str]],
) -> tuple[list[str], list[str]]:
    """Inspect effective token scope for every declared role container.

    Args:
        client: Authenticated Keycloak Admin client.
        backend_uuid: Confidential backend client UUID.
        desired_clients: Exact desired roles keyed by role-owning client ID.

    Returns:
        Missing and unexpected effective qualified role names.

    Raises:
        KeycloakRoleError: If a role owner or effective mapping is invalid.
    """

    escaped_backend = urllib.parse.quote(backend_uuid, safe="")
    missing: list[str] = []
    unexpected: list[str] = []
    for client_id, desired_roles in desired_clients.items():
        role_client_uuid = _resolve_client_uuid(client, client_id)
        escaped_role_client = urllib.parse.quote(role_client_uuid, safe="")
        path = _realm_path(
            client.identity,
            f"/clients/{escaped_backend}/evaluate-scopes/scope-mappings/"
            f"{escaped_role_client}/granted",
        )
        granted = _load_assigned_role_names(client, path)
        missing.extend(
            f"effective-scope:{client_id}/{role}"
            for role in sorted(desired_roles - granted)
        )
        unexpected.extend(
            f"effective-scope:{client_id}/{role}"
            for role in sorted(granted - desired_roles)
        )
    return missing, unexpected


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


def _role_group_paths(
    client: _AdminClient,
    user_uuid: str,
    backend_uuid: str,
    role_client_id: str,
) -> tuple[str, str, str]:
    """Build assignment, dedicated-scope, and role-definition paths.

    Args:
        client: Authenticated Keycloak Admin client.
        user_uuid: Escaped service-account user UUID.
        backend_uuid: Confidential backend client UUID.
        role_client_id: Public ID of the role-owning client.

    Returns:
        Service-account assignment path, backend dedicated-scope path, and
        role-definition path.
    """

    role_client_uuid = _resolve_client_uuid(client, role_client_id)
    escaped_role_client = urllib.parse.quote(role_client_uuid, safe="")
    escaped_backend = urllib.parse.quote(backend_uuid, safe="")
    assignment_path = _realm_path(
        client.identity,
        f"/users/{user_uuid}/role-mappings/clients/{escaped_role_client}",
    )
    scope_path = _realm_path(
        client.identity,
        f"/clients/{escaped_backend}/scope-mappings/clients/"
        f"{escaped_role_client}",
    )
    roles_path = _realm_path(
        client.identity,
        f"/clients/{escaped_role_client}/roles",
    )
    return assignment_path, scope_path, roles_path


def _ensure_exact_mapping(
    client: _AdminClient,
    mapping_path: str,
    roles_path: str,
    desired_roles: tuple[str, ...],
    mapping_label: str,
) -> bool:
    """Reconcile one exact role mapping without silently removing grants.

    Args:
        client: Authenticated Keycloak Admin client.
        mapping_path: Assignment or dedicated-scope endpoint.
        roles_path: Role-owning client roles endpoint.
        desired_roles: Exact allowed roles for the mapping.
        mapping_label: Secret-free operator label used in errors.

    Returns:
        Whether missing role grants were added.

    Raises:
        KeycloakRoleError: If existing grants exceed the declaration.
    """

    assigned = _load_assigned_role_names(client, mapping_path)
    desired = set(desired_roles)
    unexpected = sorted(assigned - desired)
    if unexpected:
        raise KeycloakRoleError(
            f"Backend {mapping_label} has undeclared roles: "
            f"{', '.join(unexpected)}."
        )
    missing = sorted(desired - assigned)
    if not missing:
        return False
    client.request(
        "POST",
        mapping_path,
        body=_load_role_representations(client, roles_path, missing),
        expected=(204,),
    )
    return True


def _ensure_role_group(
    client: _AdminClient,
    user_uuid: str,
    backend_uuid: str,
    role_client_id: str,
    desired_roles: tuple[str, ...],
) -> bool:
    """Reconcile service-account assignment and dedicated client scope.

    Args:
        client: Authenticated Keycloak Admin client.
        user_uuid: Escaped service-account user UUID.
        backend_uuid: Confidential backend client UUID.
        role_client_id: Public ID of the role-owning client.
        desired_roles: Exact allowed roles for that client.

    Returns:
        Whether either required mapping changed.

    Raises:
        KeycloakRoleError: If either mapping exceeds the declaration.
    """

    assignment_path, scope_path, roles_path = _role_group_paths(
        client,
        user_uuid,
        backend_uuid,
        role_client_id,
    )
    assignment_changed = _ensure_exact_mapping(
        client,
        assignment_path,
        roles_path,
        desired_roles,
        f"service account on {role_client_id!r}",
    )
    scope_changed = _ensure_exact_mapping(
        client,
        scope_path,
        roles_path,
        desired_roles,
        f"client scope on {role_client_id!r}",
    )
    return assignment_changed or scope_changed


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
    differences = _inspect_role_state(
        client,
        backend_uuid,
        user_uuid,
        include_effective=True,
    )
    if differences["unexpected"]:
        raise KeycloakRoleError(
            "Backend service account has undeclared roles: "
            + ", ".join(differences["unexpected"])
            + "."
        )
    changed = False
    for role_client_id, desired_roles in (
        client.identity.service_account_client_roles
    ):
        if _ensure_role_group(
            client,
            user_uuid,
            backend_uuid,
            role_client_id,
            desired_roles,
        ):
            changed = True
    return "updated" if changed else "kept"


def _inspect_role_state(
    client: _AdminClient,
    backend_uuid: str,
    user_uuid: str,
    *,
    include_effective: bool,
) -> dict[str, tuple[str, ...]]:
    """Inspect complete service-account and dedicated-scope inventories.

    Args:
        client: Authenticated Keycloak Admin client.
        backend_uuid: Confidential backend client UUID.
        user_uuid: Escaped service-account user UUID.
        include_effective: Inspect token-effective role scopes when true.

    Returns:
        Secret-free missing and unexpected qualified role names.

    Raises:
        KeycloakRoleError: If Keycloak returns malformed mapping data.
    """

    desired = {
        client_id: set(roles)
        for client_id, roles in client.identity.service_account_client_roles
    }
    escaped_backend = urllib.parse.quote(backend_uuid, safe="")
    assignments = _load_mapping_inventory(
        client,
        _realm_path(client.identity, f"/users/{user_uuid}/role-mappings"),
        "service-account",
    )
    scopes = _load_mapping_inventory(
        client,
        _realm_path(
            client.identity,
            f"/clients/{escaped_backend}/scope-mappings",
        ),
        "client-scope",
    )
    assignment_diff = _inventory_differences(
        assignments,
        desired,
        {f"default-roles-{client.identity.realm}"},
        "service-account",
    )
    scope_diff = _inventory_differences(
        scopes,
        desired,
        set(),
        "client-scope",
    )
    direct_missing = [*assignment_diff[0], *scope_diff[0]]
    direct_unexpected = [*assignment_diff[1], *scope_diff[1]]
    if direct_unexpected:
        return {
            "missing": tuple(direct_missing),
            "unexpected": tuple(direct_unexpected),
        }
    if not include_effective:
        return {
            "missing": tuple(direct_missing),
            "unexpected": (),
        }
    effective_diff = _effective_scope_differences(
        client,
        backend_uuid,
        desired,
    )
    return {
        "missing": tuple([*direct_missing, *effective_diff[0]]),
        "unexpected": tuple(effective_diff[1]),
    }


def inspect_service_account_roles(
    client: _AdminClient,
    backend_uuid: str,
    *,
    include_effective: bool = True,
) -> dict[str, tuple[str, ...]]:
    """Inspect missing and unexpected declared client-role grants.

    Args:
        client: Authenticated Keycloak Admin client.
        backend_uuid: Confidential backend client UUID.
        include_effective: Inspect token-effective role scopes when true.

    Returns:
        Secret-free ``missing`` and ``unexpected`` qualified role names.

    Raises:
        KeycloakRoleError: If Keycloak returns invalid client or role data.
    """

    user_uuid = _service_account_user_id(client, backend_uuid)
    return _inspect_role_state(
        client,
        backend_uuid,
        user_uuid,
        include_effective=include_effective,
    )


def verify_service_account_roles(
    client: _AdminClient,
    backend_uuid: str,
) -> None:
    """Require exact profile-declared backend service-account roles.

    Args:
        client: Authenticated Keycloak Admin client.
        backend_uuid: Confidential backend client UUID.

    Returns:
        Nothing when every declared role group matches exactly.

    Raises:
        KeycloakRoleError: If a role is missing, unexpected, or unreadable.
    """

    differences = inspect_service_account_roles(client, backend_uuid)
    unexpected = differences["unexpected"]
    if unexpected:
        raise KeycloakRoleError(
            "Backend service account has undeclared roles: "
            + ", ".join(unexpected)
            + "."
        )
    missing = differences["missing"]
    if missing:
        raise KeycloakRoleError(
            "Backend service account is missing declared roles: "
            + ", ".join(missing)
            + "."
        )


__all__ = [
    "KeycloakRoleError",
    "ensure_service_account_roles",
    "inspect_service_account_roles",
    "verify_service_account_roles",
]
