"""
Module: executable_profile_keycloak_validation.py

Description:
    Validates the Keycloak portion of a schema-5 executable site profile.
    Network primitives are injected by the parent configuration validator so
    this module owns Keycloak policy without duplicating shared URL rules.

Dependencies:
    - Python standard library.
    - scripts/executable_profile_support.py.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from executable_profile_support import (
    NAME_PATTERN,
    ExecutableProfileError,
    mapping,
    require_keys,
    sequence,
    text,
)


#
# Realm fields that an application profile may own.
# Platform-wide settings and identity providers remain outside this allowlist.
#
KEYCLOAK_REALM_SETTING_FIELDS = {
    "enabled",
    "registrationAllowed",
    "resetPasswordAllowed",
    "rememberMe",
    "verifyEmail",
    "loginWithEmailAllowed",
}

KEYCLOAK_RESERVED_MANAGED_CLIENT_IDS = {
    "account",
    "account-console",
    "admin-cli",
    "broker",
    "realm-management",
    "security-admin-console",
}


def _protected_values(
    protected: Mapping[str, object],
    key: str,
) -> set[str]:
    """Normalize one protected-identity string set.

    Args:
        protected: Protected identity mapping.
        key: Array field name within that mapping.

    Returns:
        Unique validated values.
    """

    field = f"auth.protectedIdentity.{key}"
    return {
        text(value, f"{field}[{index}]")
        for index, value in enumerate(
            sequence(protected.get(key, []), field)
        )
    }


def _validate_protected_origins(
    origins: set[str],
    validate_origin: Callable[[str, str], None],
) -> None:
    """Validate every protected legacy browser origin.

    Args:
        origins: Protected browser origins.
        validate_origin: Shared exact-origin validator.

    Returns:
        Nothing after all origins pass.
    """

    for index, origin in enumerate(sorted(origins)):
        validate_origin(
            origin,
            f"auth.protectedIdentity.origins[{index}]",
        )


def _validate_protected_identity(
    auth: Mapping[str, object],
    realm: str,
    validate_origin: Callable[[str, str], None],
) -> None:
    """Reject target identity intersecting profile-protected legacy data.

    Args:
        auth: Validated Keycloak mapping.
        realm: Candidate realm.
        validate_origin: Shared exact-origin validator.

    Raises:
        ExecutableProfileError: If realm, clients, or origins intersect.
    """

    protected = mapping(
        auth.get("protectedIdentity", {}),
        "auth.protectedIdentity",
    )
    protected_realms = _protected_values(protected, "realms")
    protected_clients = _protected_values(protected, "clientIds")
    protected_origins = _protected_values(protected, "origins")
    _validate_protected_origins(protected_origins, validate_origin)
    if realm in protected_realms:
        raise ExecutableProfileError(
            "auth.realm must not target a protected realm."
        )
    candidate_clients = {
        str(auth["frontendClientId"]),
        str(auth["audience"]),
        str(auth["adminClientId"]),
    }
    if candidate_clients & protected_clients:
        raise ExecutableProfileError(
            "Candidate Keycloak client identity intersects protected clients."
        )
    if set(str(value) for value in auth["webOrigins"]) & protected_origins:
        raise ExecutableProfileError(
            "Candidate Keycloak origin intersects protected origins."
        )


def _validate_service_account_roles(auth: Mapping[str, object]) -> None:
    """Validate backend service-account client-role declarations.

    Args:
        auth: Validated Keycloak mapping.

    Raises:
        ExecutableProfileError: If role owner or role names are unsafe.
    """

    role_groups = mapping(
        auth.get("serviceAccountClientRoles", {}),
        "auth.serviceAccountClientRoles",
    )
    for client_id, raw_roles in role_groups.items():
        if not NAME_PATTERN.fullmatch(
            text(client_id, "auth.serviceAccountClientRoles client")
        ):
            raise ExecutableProfileError(
                "auth.serviceAccountClientRoles contains an unsafe client ID."
            )
        roles = [
            text(
                role,
                f"auth.serviceAccountClientRoles.{client_id}[{index}]",
            )
            for index, role in enumerate(
                sequence(
                    raw_roles,
                    f"auth.serviceAccountClientRoles.{client_id}",
                )
            )
        ]
        if not roles or len(roles) != len(set(roles)):
            raise ExecutableProfileError(
                "Service-account client roles must be non-empty and unique."
            )
        if any(not NAME_PATTERN.fullmatch(role) for role in roles):
            raise ExecutableProfileError(
                "Service-account client roles contain an unsafe role name."
            )


def _validate_bootstrap_policy(auth: Mapping[str, object]) -> None:
    """Validate profile-owned realm settings and bootstrap guardrails.

    Args:
        auth: Profile authentication mapping.

    Raises:
        ExecutableProfileError: If realm settings, mapper identity, or
            forbidden usernames are incomplete or unsafe.
    """

    text(auth["realmDisplayName"], "auth.realmDisplayName")
    mapper_name = text(auth["audienceMapperName"], "auth.audienceMapperName")
    if not NAME_PATTERN.fullmatch(mapper_name):
        raise ExecutableProfileError("auth.audienceMapperName is unsafe.")
    settings = mapping(auth["realmSettings"], "auth.realmSettings")
    require_keys(
        settings,
        KEYCLOAK_REALM_SETTING_FIELDS,
        "auth.realmSettings",
    )
    unexpected = sorted(set(settings) - KEYCLOAK_REALM_SETTING_FIELDS)
    if unexpected:
        raise ExecutableProfileError(
            "auth.realmSettings contains unsupported fields: "
            + ", ".join(unexpected)
        )
    for name, value in settings.items():
        if not isinstance(value, bool):
            raise ExecutableProfileError(
                f"auth.realmSettings.{name} must be boolean."
            )
    if settings["enabled"] is not True:
        raise ExecutableProfileError(
            "auth.realmSettings.enabled must be true for deployment."
        )
    forbidden = [
        text(value, f"auth.forbiddenDefaultUsernames[{index}]")
        for index, value in enumerate(
            sequence(
                auth["forbiddenDefaultUsernames"],
                "auth.forbiddenDefaultUsernames",
            )
        )
    ]
    if len(forbidden) != len(set(forbidden)):
        raise ExecutableProfileError(
            "auth.forbiddenDefaultUsernames must be unique."
        )
    if any(not NAME_PATTERN.fullmatch(value) for value in forbidden):
        raise ExecutableProfileError(
            "auth.forbiddenDefaultUsernames contains an unsafe username."
        )


def _validate_urls(
    auth: Mapping[str, object],
    realm: str,
    validate_https: Callable[[str, str], None],
) -> None:
    """Validate server, issuer, and JWKS relationships.

    Args:
        auth: Profile authentication mapping.
        realm: Validated realm identifier.
        validate_https: Shared production HTTPS validator.

    Raises:
        ExecutableProfileError: If URLs are unsafe or inconsistent.
    """

    for field in ("serverUrl", "issuerUrl", "jwksUrl"):
        validate_https(text(auth[field], f"auth.{field}"), f"auth.{field}")
    issuer = str(auth["issuerUrl"]).rstrip("/")
    if issuer != f"{str(auth['serverUrl']).rstrip('/')}/realms/{realm}":
        raise ExecutableProfileError(
            "auth.issuerUrl must match serverUrl and realm."
        )
    expected_jwks = f"{issuer}/protocol/openid-connect/certs"
    if str(auth["jwksUrl"]).rstrip("/") != expected_jwks:
        raise ExecutableProfileError(
            "auth.jwksUrl must match the declared issuer."
        )


def _validate_callbacks(
    auth: Mapping[str, object],
    validate_redirect_uri: Callable[[str, str], None],
    validate_origin: Callable[[str, str], None],
) -> None:
    """Validate exact frontend callbacks and browser origins.

    Args:
        auth: Profile authentication mapping.
        validate_redirect_uri: Shared callback validator.
        validate_origin: Shared exact-origin validator.

    Raises:
        ExecutableProfileError: If callbacks or origins are absent or unsafe.
    """

    redirects = sequence(auth["redirectUris"], "auth.redirectUris")
    if not redirects:
        raise ExecutableProfileError("auth.redirectUris must not be empty.")
    for index, redirect_uri in enumerate(redirects):
        validate_redirect_uri(
            text(redirect_uri, f"auth.redirectUris[{index}]"),
            f"auth.redirectUris[{index}]",
        )
    for index, origin in enumerate(
        sequence(auth["webOrigins"], "auth.webOrigins")
    ):
        validate_origin(
            text(origin, f"auth.webOrigins[{index}]"),
            f"auth.webOrigins[{index}]",
        )


def validate_keycloak_auth(
    auth: Mapping[str, object],
    *,
    validate_https: Callable[[str, str], None],
    validate_origin: Callable[[str, str], None],
    validate_redirect_uri: Callable[[str, str], None],
) -> None:
    """Validate generic Keycloak realm/client/bootstrap metadata.

    Args:
        auth: Profile authentication mapping.
        validate_https: Shared production HTTPS validator.
        validate_origin: Shared exact-origin validator.
        validate_redirect_uri: Shared callback validator.

    Raises:
        ExecutableProfileError: If public OIDC identity is incomplete or unsafe.
    """

    require_keys(
        auth,
        {
            "provider",
            "serverUrl",
            "issuerUrl",
            "jwksUrl",
            "realm",
            "realmDisplayName",
            "realmSettings",
            "frontendClientId",
            "audience",
            "audienceMapperName",
            "adminClientId",
            "redirectUris",
            "webOrigins",
            "forbiddenDefaultUsernames",
            "serviceAccountClientRoles",
        },
        "auth",
    )
    realm = text(auth["realm"], "auth.realm")
    if not NAME_PATTERN.fullmatch(realm):
        raise ExecutableProfileError("auth.realm is unsafe.")
    if realm == "master":
        raise ExecutableProfileError(
            "auth.realm must not target Keycloak's master realm."
        )
    _validate_urls(auth, realm, validate_https)
    for field in ("frontendClientId", "audience", "adminClientId"):
        if not NAME_PATTERN.fullmatch(text(auth[field], f"auth.{field}")):
            raise ExecutableProfileError(f"auth.{field} is unsafe.")
    if auth["frontendClientId"] == auth["adminClientId"]:
        raise ExecutableProfileError(
            "auth.frontendClientId and auth.adminClientId must differ."
        )
    managed_clients = {
        str(auth["frontendClientId"]),
        str(auth["adminClientId"]),
    }
    reserved_clients = sorted(
        managed_clients & KEYCLOAK_RESERVED_MANAGED_CLIENT_IDS
    )
    if reserved_clients:
        raise ExecutableProfileError(
            "Managed Keycloak client IDs must not use built-in clients: "
            + ", ".join(reserved_clients)
        )
    _validate_callbacks(auth, validate_redirect_uri, validate_origin)
    _validate_protected_identity(auth, realm, validate_origin)
    _validate_bootstrap_policy(auth)
    _validate_service_account_roles(auth)


__all__ = [
    "KEYCLOAK_REALM_SETTING_FIELDS",
    "validate_keycloak_auth",
]
