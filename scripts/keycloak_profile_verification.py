"""
Module: keycloak_profile_verification.py

Description:
    Builds a secret-free, read-only Keycloak reconciliation plan and verifies
    the resulting realm, clients, audience mapper, application roles,
    frontend role scope, temporary users, service-account roles, issuer, JWKS,
    and bootstrap-owned state. Usernames reserved from automated bootstrap are
    input policy only: an existing live account is never treated as disposable
    or converted into a deletion blocker. Success requires observed state, not
    only successful mutation response codes.

Dependencies:
    - Python standard library.
    - Keycloak profile client, reconciliation, application-access, scope, and
      service-account role modules.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Mapping
from typing import Any

from keycloak_profile_client import (
    KeycloakAdminClient,
    KeycloakIdentity,
    KeycloakProfileError,
    realm_path,
    resolve_client_uuid,
)
from keycloak_profile_application_access import (
    inspect_bootstrap_test_users,
    inspect_realm_roles,
    summarize_actions,
    verify_application_access,
)
from keycloak_profile_reconciliation import (
    audience_mapper_payload,
    backend_payload,
    frontend_payload,
    owned_field_mismatches,
    owned_fields_match,
    realm_payload,
)
from keycloak_profile_realm_role_scope import (
    inspect_frontend_realm_role_scope,
    verify_frontend_realm_role_scope,
)
from keycloak_profile_roles import (
    KeycloakRoleError,
    inspect_service_account_roles,
    verify_service_account_roles,
)
from keycloak_profile_realm_configuration import DEFAULT_THEME
from keycloak_profile_theme_inventory import load_available_themes


def _read_realm(
    client: KeycloakAdminClient,
) -> dict[str, Any] | None:
    """Read the selected realm without treating absence as an error.

    Args:
        client: Authenticated Keycloak Admin client.

    Returns:
        Realm representation, or ``None`` when it does not exist.

    Raises:
        KeycloakProfileError: If Keycloak returns malformed realm data.
    """

    status, payload = client.request(
        "GET",
        realm_path(client.identity),
        expected=(200, 404),
    )
    if status == 404:
        return None
    if not isinstance(payload, dict):
        raise KeycloakProfileError(
            "Keycloak realm lookup returned invalid data."
        )
    return payload


def _read_client(
    client: KeycloakAdminClient,
    client_id: str,
) -> tuple[str, dict[str, Any]] | None:
    """Read one exact client representation.

    Args:
        client: Authenticated Keycloak Admin client.
        client_id: Exact public client identifier.

    Returns:
        UUID plus representation, or ``None`` when missing.

    Raises:
        KeycloakProfileError: If Keycloak returns malformed client data.
    """

    client_uuid = resolve_client_uuid(client, client_id)
    if client_uuid is None:
        return None
    escaped_uuid = urllib.parse.quote(client_uuid, safe="")
    _, payload = client.request(
        "GET",
        realm_path(client.identity, f"/clients/{escaped_uuid}"),
    )
    if not isinstance(payload, dict):
        raise KeycloakProfileError(
            f"Keycloak client {client_id!r} returned invalid data."
        )
    return client_uuid, payload


def _component_action(
    current: dict[str, Any] | None,
    desired: dict[str, Any],
) -> str:
    """Classify one desired representation without mutation.

    Args:
        current: Current representation, or ``None`` when missing.
        desired: Exact profile-owned desired fields.

    Returns:
        ``create``, ``update``, or ``keep``.
    """

    if current is None:
        return "create"
    if owned_fields_match(current, desired):
        return "keep"
    return "update"


def _read_mapper_action(
    client: KeycloakAdminClient,
    frontend_uuid: str | None,
) -> str:
    """Classify the declared audience mapper without mutation.

    Args:
        client: Authenticated Keycloak Admin client.
        frontend_uuid: Existing frontend UUID, or ``None`` when missing.

    Returns:
        ``create``, ``update``, or ``keep``.

    Raises:
        KeycloakProfileError: If mapper data is malformed or ambiguous.
    """

    if frontend_uuid is None:
        return "create"
    escaped_uuid = urllib.parse.quote(frontend_uuid, safe="")
    path = realm_path(
        client.identity,
        f"/clients/{escaped_uuid}/protocol-mappers/models",
    )
    _, payload = client.request("GET", path)
    if not isinstance(payload, list):
        raise KeycloakProfileError(
            "Keycloak protocol mapper lookup returned invalid data."
        )
    desired = audience_mapper_payload(client.identity)
    matches = [
        item
        for item in payload
        if isinstance(item, dict) and item.get("name") == desired["name"]
    ]
    if not matches:
        return "create"
    if len(matches) != 1:
        raise KeycloakProfileError(
            "The declared Keycloak audience mapper is ambiguous."
        )
    return _component_action(matches[0], desired)


def _role_plan(
    client: KeycloakAdminClient,
    backend: tuple[str, dict[str, Any]] | None,
) -> tuple[str, tuple[str, ...]]:
    """Classify service-account roles and expose unsafe blockers.

    Args:
        client: Authenticated Keycloak Admin client.
        backend: Existing backend UUID/representation pair, or ``None``.

    Returns:
        Planned action and any unexpected qualified role names.
    """

    backend_uuid = _role_ready_uuid(backend)
    if backend_uuid is None:
        return "assign", ()
    include_effective = backend[1].get("fullScopeAllowed") is not True
    differences = inspect_service_account_roles(
        client,
        backend_uuid,
        include_effective=include_effective,
    )
    action = "assign" if differences["missing"] else "keep"
    return action, differences["unexpected"]


def _secret_plan_action(
    docker_secret_present: bool,
    replace_secret: bool,
) -> str:
    """Classify the Docker secret handoff without reading secret material.

    Args:
        docker_secret_present: Whether the declared Docker secret exists.
        replace_secret: Whether explicit rotation was requested.

    Returns:
        Sanitized secret action.
    """

    if replace_secret:
        return "rotate-and-replace"
    if docker_secret_present:
        return "keep-present-unverified"
    return "fetch-prove-and-create"


def _plan_blockers(
    client: KeycloakAdminClient,
    *,
    backend_action: str,
    unexpected_roles: tuple[str, ...],
    docker_secret_present: bool,
    replace_secret: bool,
) -> list[str]:
    """Build explicit blockers that require operator correction.

    Args:
        client: Authenticated Keycloak Admin client.
        backend_action: Planned backend client action.
        unexpected_roles: Undeclared qualified service-account roles.
        docker_secret_present: Whether the declared Docker secret exists.
        replace_secret: Whether explicit rotation was requested.

    Returns:
        Sanitized blocker messages.
    """

    blockers = [
        f"Remove undeclared service-account role explicitly: {role}"
        for role in unexpected_roles
    ]
    realm_enabled = dict(client.identity.realm_settings)["enabled"]
    if not realm_enabled and (replace_secret or not docker_secret_present):
        blockers.append(
            "Enable the realm for one bootstrap run before creating or "
            "rotating the proven Docker client secret."
        )
    if (
        backend_action == "create"
        and docker_secret_present
        and not replace_secret
    ):
        blockers.append(
            "Backend client is missing while its Docker secret exists; "
            "use explicit secret rotation with the stack stopped."
        )
    blockers.extend(_theme_availability_blockers(client))
    return blockers


def _plan_warnings(
    client: KeycloakAdminClient,
    *,
    email_sender_present: bool,
) -> list[str]:
    """Build non-blocking operator follow-up warnings.

    Args:
        client: Authenticated Keycloak Admin client.
        email_sender_present: Whether live realm state contains a usable public
            SMTP sender map.

    Returns:
        Sanitized warnings that do not prevent unrelated reconciliation.
    """

    warnings: list[str] = []
    realm_settings = dict(client.identity.realm_settings)
    email_delivery_required = bool(
        realm_settings["verifyEmail"]
        or realm_settings["resetPasswordAllowed"]
    )
    if (
        email_delivery_required
        and not client.identity.email_sender_settings.enabled
        and not email_sender_present
    ):
        warnings.append(
            "Email verification or password reset is enabled without a "
            "managed or existing SMTP sender; configure and test email "
            "delivery before relying on those features."
        )
    return warnings


def _realm_has_email_sender(
    current_realm: dict[str, Any] | None,
) -> bool:
    """Check whether a live realm exposes minimum public SMTP configuration.

    Password material is deliberately irrelevant to this read-only check:
    Keycloak does not return the stored SMTP password through ordinary realm
    reads. Authenticated senders are proved later through the SMTP connection
    test or the mandatory Admin UI verification step.

    Args:
        current_realm: Existing realm representation, or ``None`` for a new
            realm.

    Returns:
        ``True`` when both SMTP host and sender address are present.
    """

    if current_realm is None:
        return False
    smtp_server = current_realm.get("smtpServer")
    if not isinstance(smtp_server, dict):
        return False
    return all(
        isinstance(smtp_server.get(key), str)
        and bool(smtp_server[key].strip())
        for key in ("host", "from")
    )


def _theme_availability_blockers(
    client: KeycloakAdminClient,
) -> list[str]:
    """Require every non-default selected theme to exist on the live server.

    Args:
        client: Authenticated Keycloak Admin client.

    Returns:
        Sanitized blockers naming unavailable theme selections.

    Raises:
        KeycloakProfileError: If server information cannot be read safely.
    """

    selected = client.identity.theme_settings
    requested = {
        "login": selected.login,
        "account": selected.account,
        "admin": selected.admin,
        "email": selected.email,
    }
    custom = {
        theme_type: name
        for theme_type, name in requested.items()
        if name != DEFAULT_THEME
    }
    if not custom:
        return []
    inventory = load_available_themes(client)
    blockers: list[str] = []
    for theme_type, name in custom.items():
        available = inventory[theme_type]
        if name not in available:
            visible = ", ".join(sorted(available)) or "none reported"
            blockers.append(
                f"Install or select an available {theme_type} theme; "
                f"{name!r} is unavailable (available: {visible})."
            )
    return blockers


def _read_plan_clients(
    client: KeycloakAdminClient,
    realm_exists: bool,
) -> tuple[
    tuple[str, dict[str, Any]] | None,
    tuple[str, dict[str, Any]] | None,
]:
    """Read candidate clients only when their realm exists.

    Args:
        client: Authenticated Keycloak Admin client.
        realm_exists: Whether client endpoints are available.

    Returns:
        Optional frontend and backend UUID/representation pairs.
    """

    if not realm_exists:
        return None, None
    identity = client.identity
    return (
        _read_client(client, identity.frontend_client_id),
        _read_client(client, identity.backend_client_id),
    )


def _role_ready_uuid(
    backend: tuple[str, dict[str, Any]] | None,
) -> str | None:
    """Return a backend UUID only when its service account is available.

    Args:
        backend: Optional backend UUID/representation pair.

    Returns:
        Backend UUID, or ``None`` when role inspection must wait for apply.
    """

    if backend is None:
        return None
    if backend[1].get("serviceAccountsEnabled") is not True:
        return None
    return backend[0]


def _application_access_plan(
    client: KeycloakAdminClient,
    *,
    realm_exists: bool,
    frontend_uuid: str | None,
) -> tuple[dict[str, object], dict[str, str]]:
    """Inspect application roles, frontend scope, and temporary users.

    Args:
        client: Authenticated Keycloak Admin client.
        realm_exists: Whether application access endpoints are available.
        frontend_uuid: Existing public-client UUID, or ``None`` when missing.

    Returns:
        Sanitized plan fields and the detailed test-user action map used for
        credential collection and post-apply cleanup tracking.

    Raises:
        KeycloakApplicationAccessError: If live role or user data is malformed.
    """

    realm_roles = inspect_realm_roles(client, realm_exists=realm_exists)
    test_users = inspect_bootstrap_test_users(
        client,
        realm_exists=realm_exists,
    )
    return (
        {
            "realmRoles": summarize_actions(realm_roles),
            "realmRoleActions": realm_roles,
            "frontendRealmRoleScope": inspect_frontend_realm_role_scope(
                client,
                frontend_uuid,
            ),
            "bootstrapTestUsers": summarize_actions(test_users),
            "bootstrapTestUserActions": test_users,
        },
        test_users,
    )


def _managed_client_plan(
    client: KeycloakAdminClient,
    *,
    realm_exists: bool,
) -> tuple[dict[str, str], str | None, str, tuple[str, ...]]:
    """Inspect both managed clients, mapper, and service-account roles.

    Args:
        client: Authenticated Keycloak Admin client.
        realm_exists: Whether client endpoints are currently available.

    Returns:
        Sanitized client plan fields, frontend UUID, backend action, and
        undeclared service-account roles used for blockers.

    Raises:
        KeycloakProfileError: If client or mapper state is malformed.
        KeycloakRoleError: If service-account roles cannot be inspected safely.
    """

    identity = client.identity
    frontend, backend = _read_plan_clients(client, realm_exists)
    frontend_uuid = None if frontend is None else frontend[0]
    role_action, unexpected_roles = _role_plan(client, backend)
    frontend_action = _component_action(
        None if frontend is None else frontend[1],
        frontend_payload(identity),
    )
    backend_action = _component_action(
        None if backend is None else backend[1],
        backend_payload(identity),
    )
    return (
        {
            "frontendClient": frontend_action,
            "backendClient": backend_action,
            "audienceMapper": _read_mapper_action(client, frontend_uuid),
            "serviceAccountRoles": role_action,
        },
        frontend_uuid,
        backend_action,
        unexpected_roles,
    )


def build_reconciliation_plan(
    client: KeycloakAdminClient,
    *,
    docker_secret_present: bool,
    replace_secret: bool,
) -> dict[str, Any]:
    """Build one sanitized read-only plan from live Keycloak and Docker state.

    Args:
        client: Authenticated Keycloak Admin client.
        docker_secret_present: Whether the declared Docker secret exists.
        replace_secret: Whether explicit credential rotation was requested.

    Returns:
        JSON-compatible plan with component actions and blockers.

    Raises:
        KeycloakProfileError: If live state is malformed.
        KeycloakApplicationAccessError: If application role or user state is
            malformed.
        KeycloakRoleError: If role state cannot be inspected safely.
    """

    identity = client.identity
    current_realm = _read_realm(client)
    realm_exists = current_realm is not None
    realm_action = _component_action(
        current_realm,
        realm_payload(identity),
    )
    client_plan, frontend_uuid, backend_action, unexpected_roles = (
        _managed_client_plan(
            client,
            realm_exists=realm_exists,
        )
    )
    application_plan, _ = _application_access_plan(
        client,
        realm_exists=realm_exists,
        frontend_uuid=frontend_uuid,
    )
    blockers = _plan_blockers(
        client,
        backend_action=backend_action,
        unexpected_roles=unexpected_roles,
        docker_secret_present=docker_secret_present,
        replace_secret=replace_secret,
    )
    warnings = _plan_warnings(
        client,
        email_sender_present=_realm_has_email_sender(current_realm),
    )
    return {
        "realm": realm_action,
        "realmThemes": realm_action,
        "realmLocalization": realm_action,
        "realmEmailSender": realm_action,
        "smtpPasswordRequired": bool(
            client.identity.email_sender_settings.enabled
            and client.identity.email_sender_settings.authentication
            and realm_action != "keep"
        ),
        **client_plan,
        **application_plan,
        "dockerSecret": _secret_plan_action(
            docker_secret_present,
            replace_secret,
        ),
        "warnings": warnings,
        "blockers": blockers,
    }


def _verify_mapper(
    client: KeycloakAdminClient,
    frontend_uuid: str,
) -> None:
    """Require exactly one converged profile-owned audience mapper.

    Args:
        client: Authenticated Keycloak Admin client.
        frontend_uuid: Verified frontend client UUID.

    Returns:
        Nothing when the mapper matches.

    Raises:
        KeycloakProfileError: If the mapper is missing, ambiguous, or drifted.
    """

    action = _read_mapper_action(client, frontend_uuid)
    if action != "keep":
        raise KeycloakProfileError(
            "Keycloak audience mapper verification found unresolved drift."
        )


def _verify_realm_and_clients(
    client: KeycloakAdminClient,
) -> tuple[tuple[str, dict[str, Any]], tuple[str, dict[str, Any]]]:
    """Verify profile-owned realm and client representations.

    Args:
        client: Authenticated Keycloak Admin client.

    Returns:
        Verified frontend and backend UUID/representation pairs.

    Raises:
        KeycloakProfileError: If realm or client state is missing or drifted.
    """

    identity = client.identity
    realm = _read_realm(client)
    desired_realm = realm_payload(identity)
    if realm is None:
        raise KeycloakProfileError(
            "Keycloak realm verification found unresolved drift: realm missing."
        )
    _require_owned_fields("realm", realm, desired_realm)
    frontend = _read_client(client, identity.frontend_client_id)
    backend = _read_client(client, identity.backend_client_id)
    if frontend is None:
        raise KeycloakProfileError(
            "Keycloak frontend client verification found unresolved drift: "
            "client missing."
        )
    _require_owned_fields(
        "frontend client",
        frontend[1],
        frontend_payload(identity),
    )
    if backend is None:
        raise KeycloakProfileError(
            "Keycloak backend client verification found unresolved drift: "
            "client missing."
        )
    _require_owned_fields(
        "backend client",
        backend[1],
        backend_payload(identity),
    )
    return frontend, backend


def _require_owned_fields(
    label: str,
    current: dict[str, Any],
    desired: dict[str, Any],
) -> None:
    """Raise a secret-safe error naming every unresolved public field.

    Args:
        label: Operator-facing Keycloak component name.
        current: Live Keycloak representation.
        desired: Profile-owned public representation.

    Returns:
        Nothing when every owned field matches.

    Raises:
        KeycloakProfileError: If one or more profile-owned fields drift.
    """

    mismatches = owned_field_mismatches(current, desired)
    if mismatches:
        raise KeycloakProfileError(
            f"Keycloak {label} verification found unresolved drift in "
            f"profile-owned fields: {', '.join(mismatches)}."
        )


def _verify_public_metadata(client: KeycloakAdminClient) -> None:
    """Verify exact issuer metadata and at least one public signing key.

    Args:
        client: Authenticated Keycloak Admin client.

    Returns:
        Nothing when discovery and JWKS are valid.

    Raises:
        KeycloakProfileError: If issuer or signing-key state is invalid.
    """

    identity = client.identity
    discovery = client.public_json(
        f"{identity.issuer_url}/.well-known/openid-configuration"
    )
    jwks = client.public_json(identity.jwks_url)
    if discovery.get("issuer") != identity.issuer_url:
        raise KeycloakProfileError(
            "Keycloak discovery issuer does not match the site profile."
        )
    if not isinstance(jwks.get("keys"), list) or not jwks["keys"]:
        raise KeycloakProfileError(
            "Keycloak JWKS verification returned no signing keys."
        )


def _realm_is_enabled(identity: KeycloakIdentity) -> bool:
    """Return the selected realm-enabled setting.

    Args:
        identity: Active profile-derived Keycloak identity.

    Returns:
        Whether public OIDC metadata and token issuance should be available.
    """

    return dict(identity.realm_settings)["enabled"]


def verify_reconciled_state(
    client: KeycloakAdminClient,
) -> dict[str, bool]:
    """Verify exact Admin API state plus public issuer and signing keys.

    Args:
        client: Authenticated Keycloak Admin client.

    Returns:
        Secret-free named checks, all true on success.

    Raises:
        KeycloakProfileError: If mapper, user, issuer, or JWKS verification
            fails.
        KeycloakRoleError: If service-account roles are not exact.
    """

    frontend, backend = _verify_realm_and_clients(client)
    _verify_mapper(client, frontend[0])
    verify_frontend_realm_role_scope(client, frontend[0])
    verify_service_account_roles(client, backend[0])
    verify_application_access(client)
    realm_enabled = _realm_is_enabled(client.identity)
    if realm_enabled:
        _verify_public_metadata(client)
    return {
        "realmSettings": True,
        "realmThemes": True,
        "realmLocalization": True,
        "realmEmailSender": True,
        "frontendPkceClient": True,
        "backendServiceClient": True,
        "audienceMapper": True,
        "serviceAccountRoles": True,
        "applicationRealmRoles": True,
        "bootstrapTestUsers": True,
        "issuer": realm_enabled,
        "jwks": realm_enabled,
        "realmDisabledByOperator": not realm_enabled,
    }


__all__ = [
    "build_reconciliation_plan",
    "verify_reconciled_state",
]
