"""
Module: keycloak_profile_application_access.py

Description:
    Models and reconciles site-profile-declared application realm roles and
    explicitly temporary bootstrap test users. Passwords are supplied only at
    runtime for missing users and never enter the profile, plan, or summary.
    Interactive callers may select each declared user independently.

Dependencies:
    - Python standard library only.
    - A structural Keycloak Admin client supplied by the caller.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from typing import Any, Mapping, Protocol


class KeycloakApplicationAccessError(RuntimeError):
    """Report unsafe or incomplete application-role/test-user state."""


@dataclass(frozen=True)
class KeycloakRealmRole:
    """Describe one application realm role owned by a site profile.

    Attributes:
        name: Stable token-facing role name.
        description: Human-readable Keycloak administration description.
    """

    name: str
    description: str


@dataclass(frozen=True)
class KeycloakBootstrapTestUser:
    """Describe one secret-free temporary test-user declaration.

    Attributes:
        username: Stable Keycloak login name.
        email: Non-delivering or controlled test email address.
        first_name: Human-readable first name.
        last_name: Human-readable last name.
        enabled: Whether Keycloak permits login.
        email_verified: Whether the synthetic email is treated as verified.
        temporary_password: Whether first login must replace the password.
        realm_roles: Exact profile-owned application roles assigned to user.
        production_cleanup_required: Whether production must remove the user.
        selected_for_bootstrap: Whether this run should create or maintain the
            user. A false value never deletes an existing account silently.
    """

    username: str
    email: str
    first_name: str
    last_name: str
    enabled: bool
    email_verified: bool
    temporary_password: bool
    realm_roles: tuple[str, ...]
    production_cleanup_required: bool
    selected_for_bootstrap: bool = True


class _Identity(Protocol):
    """Describe identity fields required by application-access operations."""

    realm: str
    realm_roles: tuple[KeycloakRealmRole, ...]
    realm_role_catalog: tuple[KeycloakRealmRole, ...]
    bootstrap_test_users_enabled: bool
    bootstrap_test_users: tuple[KeycloakBootstrapTestUser, ...]


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
    """Return the full profile-owned role catalog with legacy fallback.

    Args:
        identity: Active Keycloak identity.

    Returns:
        Full role catalog, or selected roles for pre-catalog test identities.
    """

    catalog = getattr(identity, "realm_role_catalog", ())
    return catalog or identity.realm_roles


def _realm_path(identity: _Identity, suffix: str = "") -> str:
    """Build an escaped selected-realm Admin API path.

    Args:
        identity: Profile-derived Keycloak identity.
        suffix: Optional path following the realm root.

    Returns:
        Absolute Keycloak Admin API path.
    """

    realm = urllib.parse.quote(identity.realm, safe="")
    return f"/admin/realms/{realm}{suffix}"


def _role_payload(role: KeycloakRealmRole) -> dict[str, object]:
    """Build the profile-owned Keycloak realm-role fields.

    Args:
        role: Declared application role.

    Returns:
        Keycloak realm-role representation.
    """

    return {"name": role.name, "description": role.description}


def _read_role(
    client: _AdminClient,
    role: KeycloakRealmRole,
) -> dict[str, Any] | None:
    """Read one declared realm role without treating absence as an error.

    Args:
        client: Authenticated Keycloak Admin client.
        role: Declared role to read.

    Returns:
        Role representation or ``None`` when absent.

    Raises:
        KeycloakApplicationAccessError: If Keycloak returns malformed data.
    """

    escaped = urllib.parse.quote(role.name, safe="")
    status, payload = client.request(
        "GET",
        _realm_path(client.identity, f"/roles/{escaped}"),
        expected=(200, 404),
    )
    if status == 404:
        return None
    if not isinstance(payload, dict):
        raise KeycloakApplicationAccessError(
            f"Keycloak realm role {role.name!r} returned invalid data."
        )
    return payload


def _role_action(
    current: dict[str, Any] | None,
    role: KeycloakRealmRole,
) -> str:
    """Classify one declared realm role.

    Args:
        current: Live representation or ``None``.
        role: Desired role definition.

    Returns:
        ``create``, ``update``, or ``keep``.
    """

    if current is None:
        return "create"
    desired = _role_payload(role)
    return "keep" if all(current.get(k) == v for k, v in desired.items()) else "update"


def inspect_realm_roles(
    client: _AdminClient,
    *,
    realm_exists: bool,
) -> dict[str, str]:
    """Build the live action map for all declared application roles.

    Args:
        client: Authenticated Keycloak Admin client.
        realm_exists: Whether role endpoints are currently available.

    Returns:
        Role-name to action mapping.
    """

    if not realm_exists:
        return {role.name: "create" for role in client.identity.realm_roles}
    return {
        role.name: _role_action(_read_role(client, role), role)
        for role in client.identity.realm_roles
    }


def summarize_actions(actions: Mapping[str, str]) -> str:
    """Render deterministic counts for one sanitized component plan.

    Args:
        actions: Public component-name to action mapping.

    Returns:
        Comma-separated action counts or ``none declared``.
    """

    if not actions:
        return "none declared"
    counts: dict[str, int] = {}
    for action in actions.values():
        counts[action] = counts.get(action, 0) + 1
    return ", ".join(
        f"{name}={counts[name]}" for name in sorted(counts)
    )


def ensure_realm_roles(client: _AdminClient) -> str:
    """Create or update every profile-owned application realm role.

    Args:
        client: Authenticated Keycloak Admin client.

    Returns:
        Sanitized action-count summary.

    Raises:
        KeycloakApplicationAccessError: If a role cannot be inspected.
    """

    actions: dict[str, str] = {}
    roles_path = _realm_path(client.identity, "/roles")
    for role in client.identity.realm_roles:
        current = _read_role(client, role)
        action = _role_action(current, role)
        if action == "create":
            client.request(
                "POST",
                roles_path,
                body=_role_payload(role),
                expected=(201, 204),
            )
        elif action == "update":
            escaped = urllib.parse.quote(role.name, safe="")
            client.request(
                "PUT",
                f"{roles_path}/{escaped}",
                body={**current, **_role_payload(role)},
                expected=(200, 204),
            )
        actions[role.name] = action
    return summarize_actions(actions)


def _user_payload(user: KeycloakBootstrapTestUser) -> dict[str, object]:
    """Build profile-owned public Keycloak user fields.

    Args:
        user: Declared temporary test user.

    Returns:
        Keycloak user representation without credentials.
    """

    return {
        "username": user.username,
        "email": user.email,
        "firstName": user.first_name,
        "lastName": user.last_name,
        "enabled": user.enabled,
        "emailVerified": user.email_verified,
    }


def _read_user(
    client: _AdminClient,
    username: str,
) -> tuple[str, dict[str, Any]] | None:
    """Resolve one exact test user by username.

    Args:
        client: Authenticated Keycloak Admin client.
        username: Exact declared username.

    Returns:
        User UUID and representation, or ``None`` when absent.

    Raises:
        KeycloakApplicationAccessError: If the response is malformed or
            ambiguous.
    """

    _, payload = client.request(
        "GET",
        _realm_path(client.identity, "/users"),
        query={"username": username, "exact": "true"},
    )
    if not isinstance(payload, list):
        raise KeycloakApplicationAccessError(
            "Keycloak test-user lookup returned invalid data."
        )
    matches = [
        item
        for item in payload
        if isinstance(item, dict) and item.get("username") == username
    ]
    if not matches:
        return None
    if len(matches) != 1 or not isinstance(matches[0].get("id"), str):
        raise KeycloakApplicationAccessError(
            f"Keycloak test user {username!r} is ambiguous."
        )
    return str(matches[0]["id"]), matches[0]


def _read_user_realm_roles(
    client: _AdminClient,
    user_uuid: str,
) -> set[str]:
    """Read direct realm-role names assigned to one test user.

    Args:
        client: Authenticated Keycloak Admin client.
        user_uuid: Internal Keycloak user UUID.

    Returns:
        Direct realm-role names.

    Raises:
        KeycloakApplicationAccessError: If mapping data is malformed.
    """

    escaped = urllib.parse.quote(user_uuid, safe="")
    _, payload = client.request(
        "GET",
        _realm_path(client.identity, f"/users/{escaped}/role-mappings/realm"),
    )
    if not isinstance(payload, list) or any(
        not isinstance(role, dict) or not isinstance(role.get("name"), str)
        for role in payload
    ):
        raise KeycloakApplicationAccessError(
            "Keycloak test-user realm-role mapping was invalid."
        )
    return {str(role["name"]) for role in payload}


def _user_has_password(client: _AdminClient, user_uuid: str) -> bool:
    """Check whether one test user has a password credential.

    Args:
        client: Authenticated Keycloak Admin client.
        user_uuid: Internal Keycloak user UUID.

    Returns:
        True when Keycloak reports a password credential. Credential values are
        never returned by this endpoint.

    Raises:
        KeycloakApplicationAccessError: If credential metadata is malformed.
    """

    escaped = urllib.parse.quote(user_uuid, safe="")
    _, payload = client.request(
        "GET",
        _realm_path(client.identity, f"/users/{escaped}/credentials"),
    )
    if not isinstance(payload, list) or any(
        not isinstance(credential, dict)
        or not isinstance(credential.get("type"), str)
        for credential in payload
    ):
        raise KeycloakApplicationAccessError(
            "Keycloak test-user credential metadata was invalid."
        )
    return any(credential["type"] == "password" for credential in payload)


def _user_action(
    client: _AdminClient,
    user: KeycloakBootstrapTestUser,
    current: tuple[str, dict[str, Any]] | None,
) -> str:
    """Classify one enabled bootstrap test user and its application roles.

    Args:
        client: Authenticated Keycloak Admin client.
        user: Desired test-user declaration.
        current: Live UUID/representation pair or ``None``.

    Returns:
        ``create``, ``set-password``, ``update``, or ``keep``.
    """

    if current is None:
        return "create"
    if not _user_has_password(client, current[0]):
        return "set-password"
    desired = _user_payload(user)
    metadata_matches = all(current[1].get(k) == v for k, v in desired.items())
    application_roles = {
        role.name for role in _owned_role_catalog(client.identity)
    }
    assigned = _read_user_realm_roles(client, current[0]) & application_roles
    roles_match = assigned == set(user.realm_roles)
    return "keep" if metadata_matches and roles_match else "update"


def inspect_bootstrap_test_users(
    client: _AdminClient,
    *,
    realm_exists: bool,
) -> dict[str, str]:
    """Build live actions for profile-declared temporary test users.

    Args:
        client: Authenticated Keycloak Admin client.
        realm_exists: Whether user endpoints are currently available.

    Returns:
        Username to action mapping. A user not selected for this run uses
        ``skip`` regardless of live presence and is never read, changed,
        deleted, or converted into an apply blocker.
    """

    actions: dict[str, str] = {}
    for user in client.identity.bootstrap_test_users:
        selected = (
            client.identity.bootstrap_test_users_enabled
            and user.selected_for_bootstrap
        )
        if not selected:
            actions[user.username] = "skip"
            continue
        current = _read_user(client, user.username) if realm_exists else None
        actions[user.username] = _user_action(client, user, current)
    return actions


def required_test_user_passwords(actions: Mapping[str, str]) -> tuple[str, ...]:
    """List missing users whose credentials must be supplied at runtime.

    Args:
        actions: Test-user action map from live inspection.

    Returns:
        Sorted usernames requiring a new password.
    """

    password_actions = {"create", "set-password"}
    return tuple(
        sorted(
            name for name, action in actions.items() if action in password_actions
        )
    )


def _role_representations(
    client: _AdminClient,
    names: set[str],
) -> list[dict[str, Any]]:
    """Load complete realm-role representations for mapping mutations.

    Args:
        client: Authenticated Keycloak Admin client.
        names: Declared role names to resolve.

    Returns:
        Keycloak role representations in sorted order.

    Raises:
        KeycloakApplicationAccessError: If a required role is absent.
    """

    declarations = {
        role.name: role for role in _owned_role_catalog(client.identity)
    }
    representations: list[dict[str, Any]] = []
    for name in sorted(names):
        representation = _read_role(client, declarations[name])
        if representation is None:
            raise KeycloakApplicationAccessError(
                f"Declared Keycloak realm role {name!r} is missing."
            )
        representations.append(representation)
    return representations


def _reconcile_user_roles(
    client: _AdminClient,
    user_uuid: str,
    desired_roles: tuple[str, ...],
) -> None:
    """Reconcile only profile-owned application roles for one test user.

    Args:
        client: Authenticated Keycloak Admin client.
        user_uuid: Internal Keycloak user UUID.
        desired_roles: Exact desired application role names.

    Returns:
        Nothing after missing roles are added and obsolete profile roles are
        removed. Built-in and unrelated roles remain untouched.
    """

    assigned = _read_user_realm_roles(client, user_uuid)
    owned = {role.name for role in _owned_role_catalog(client.identity)}
    desired = set(desired_roles)
    escaped = urllib.parse.quote(user_uuid, safe="")
    path = _realm_path(client.identity, f"/users/{escaped}/role-mappings/realm")
    missing = desired - assigned
    obsolete = (assigned & owned) - desired
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


def _reset_user_password(
    client: _AdminClient,
    user_uuid: str,
    user: KeycloakBootstrapTestUser,
    password: str,
) -> None:
    """Set one test user's runtime-supplied password.

    Args:
        client: Authenticated Keycloak Admin client.
        user_uuid: Internal Keycloak user UUID.
        user: Test-user declaration owning temporary-password policy.
        password: Secret entered without terminal echo.

    Returns:
        Nothing after Keycloak accepts the credential.
    """

    escaped = urllib.parse.quote(user_uuid, safe="")
    client.request(
        "PUT",
        _realm_path(client.identity, f"/users/{escaped}/reset-password"),
        body={
            "type": "password",
            "value": password,
            "temporary": user.temporary_password,
        },
        expected=(204,),
    )


def _ensure_test_user(
    client: _AdminClient,
    user: KeycloakBootstrapTestUser,
    passwords: Mapping[str, str],
) -> str:
    """Create or update one test user without persisting its credential.

    Args:
        client: Authenticated Keycloak Admin client.
        user: Desired test-user declaration.
        passwords: Runtime-only passwords keyed by users needing credentials.

    Returns:
        ``create``, ``set-password``, ``update``, or ``keep`` action.

    Raises:
        KeycloakApplicationAccessError: If a required password is absent.
    """

    current = _read_user(client, user.username)
    action = _user_action(client, user, current)
    if action == "create":
        password = passwords.get(user.username, "")
        if not password:
            raise KeycloakApplicationAccessError(
                f"A password is required for new test user {user.username!r}."
            )
        client.request(
            "POST",
            _realm_path(client.identity, "/users"),
            body=_user_payload(user),
            expected=(201, 204),
        )
        current = _read_user(client, user.username)
        if current is None:
            raise KeycloakApplicationAccessError(
                f"Unable to resolve test user {user.username!r} after creation."
            )
        _reset_user_password(client, current[0], user, password)
    elif action in {"update", "set-password"} and current is not None:
        escaped = urllib.parse.quote(current[0], safe="")
        client.request(
            "PUT",
            _realm_path(client.identity, f"/users/{escaped}"),
            body={**current[1], **_user_payload(user)},
            expected=(200, 204),
        )
        if action == "set-password":
            password = passwords.get(user.username, "")
            if not password:
                raise KeycloakApplicationAccessError(
                    "A password is required to recover test user "
                    f"{user.username!r}."
                )
            _reset_user_password(client, current[0], user, password)
    if current is None:
        raise KeycloakApplicationAccessError(
            f"Test user {user.username!r} could not be reconciled."
        )
    _reconcile_user_roles(client, current[0], user.realm_roles)
    return action


def ensure_bootstrap_test_users(
    client: _AdminClient,
    passwords: Mapping[str, str],
) -> str:
    """Reconcile every enabled profile test user without automatic deletion.

    Args:
        client: Authenticated Keycloak Admin client.
        passwords: Runtime-only passwords for creation or credential recovery.

    Returns:
        Sanitized action-count summary or ``disabled``.
    """

    selected_users = tuple(
        user
        for user in client.identity.bootstrap_test_users
        if client.identity.bootstrap_test_users_enabled
        and user.selected_for_bootstrap
    )
    if not selected_users:
        return "disabled"
    actions = {
        user.username: _ensure_test_user(client, user, passwords)
        for user in selected_users
    }
    return summarize_actions(actions)


def verify_application_access(client: _AdminClient) -> None:
    """Verify application roles and the selected test-user lifecycle state.

    Args:
        client: Authenticated Keycloak Admin client.

    Returns:
        Nothing when all declared roles and users match.

    Raises:
        KeycloakApplicationAccessError: If any owned state remains drifted.
    """

    role_actions = inspect_realm_roles(client, realm_exists=True)
    drifted_roles = [name for name, action in role_actions.items() if action != "keep"]
    if drifted_roles:
        raise KeycloakApplicationAccessError(
            "Keycloak application realm roles remain drifted: "
            + ", ".join(sorted(drifted_roles))
        )
    user_actions = inspect_bootstrap_test_users(client, realm_exists=True)
    drifted_users = [
        user.username
        for user in client.identity.bootstrap_test_users
        if client.identity.bootstrap_test_users_enabled
        and user.selected_for_bootstrap
        and user_actions[user.username] != "keep"
    ]
    if drifted_users:
        raise KeycloakApplicationAccessError(
            "Keycloak bootstrap test users remain drifted: "
            + ", ".join(sorted(drifted_users))
        )


__all__ = [
    "KeycloakApplicationAccessError",
    "KeycloakBootstrapTestUser",
    "KeycloakRealmRole",
    "ensure_bootstrap_test_users",
    "ensure_realm_roles",
    "inspect_bootstrap_test_users",
    "inspect_realm_roles",
    "required_test_user_passwords",
    "summarize_actions",
    "verify_application_access",
]
