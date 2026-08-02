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

import re
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

# Complete schema-5 Keycloak authentication contract. Keeping this declaration
# separate makes the orchestration entry point a readable sequence of checks.
KEYCLOAK_AUTH_REQUIRED_FIELDS = {
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
    "realmRoles",
    "bootstrapTestUsersEnabled",
    "bootstrapTestUsers",
    "forbiddenDefaultUsernames",
    "serviceAccountClientRoles",
}

EMAIL_PATTERN = re.compile(
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?"
)

# These special-use suffixes are rejected by the backend's Pydantic EmailStr
# contract. Accepting them here would create Keycloak users that authenticate
# successfully but cannot obtain an application-owned backend profile.
BACKEND_INCOMPATIBLE_EMAIL_SUFFIXES = {
    "invalid",
    "local",
    "localhost",
    "test",
}


def is_backend_compatible_email(value: str) -> bool:
    """Validate an email accepted by the shared backend user contract.

    Args:
        value: Candidate bootstrap-user email address.

    Returns:
        True for a bounded ASCII mailbox with valid domain labels and no
        special-use suffix rejected by Pydantic's production email validator.
    """

    if len(value) > 254 or not EMAIL_PATTERN.fullmatch(value):
        return False
    local, domain = value.rsplit("@", 1)
    if len(local) > 64 or local.startswith(".") or local.endswith("."):
        return False
    if ".." in local or ".." in domain:
        return False
    labels = domain.lower().split(".")
    if len(labels) < 2 or any(
        not label
        or len(label) > 63
        or not label[0].isalnum()
        or not label[-1].isalnum()
        for label in labels
    ):
        return False
    return labels[-1] not in BACKEND_INCOMPATIBLE_EMAIL_SUFFIXES


def _validate_realm_roles(auth: Mapping[str, object]) -> set[str]:
    """Validate profile-owned application realm-role declarations.

    Args:
        auth: Profile authentication mapping.

    Returns:
        Unique declared realm-role names.

    Raises:
        ExecutableProfileError: If role metadata is malformed or duplicated.
    """

    role_names: list[str] = []
    for index, raw_role in enumerate(
        sequence(auth["realmRoles"], "auth.realmRoles")
    ):
        field = f"auth.realmRoles[{index}]"
        role = mapping(raw_role, field)
        allowed = {"name", "description"}
        require_keys(role, allowed, field)
        unsupported = sorted(set(role) - allowed)
        if unsupported:
            raise ExecutableProfileError(
                f"{field} contains unsupported fields: "
                + ", ".join(unsupported)
            )
        name = text(role["name"], f"auth.realmRoles[{index}].name")
        description = text(
            role["description"],
            f"auth.realmRoles[{index}].description",
        )
        if not NAME_PATTERN.fullmatch(name):
            raise ExecutableProfileError(
                f"auth.realmRoles[{index}].name is unsafe."
            )
        if len(description) > 256:
            raise ExecutableProfileError(
                f"auth.realmRoles[{index}].description is too long."
            )
        role_names.append(name)
    if len(role_names) != len(set(role_names)):
        raise ExecutableProfileError("auth.realmRoles names must be unique.")
    return set(role_names)


def _validate_test_user_identity(
    user: Mapping[str, object],
    index: int,
) -> tuple[str, str]:
    """Validate one test user's public identity and lifecycle booleans.

    Args:
        user: Secret-free test-user mapping.
        index: Position used in precise validation errors.

    Returns:
        Validated username and email.

    Raises:
        ExecutableProfileError: If public metadata or cleanup policy is unsafe.
    """

    field = f"auth.bootstrapTestUsers[{index}]"
    username = text(user["username"], f"{field}.username")
    email = text(user["email"], f"{field}.email")
    text(user["firstName"], f"{field}.firstName")
    text(user["lastName"], f"{field}.lastName")
    if not NAME_PATTERN.fullmatch(username):
        raise ExecutableProfileError(f"{field}.username is unsafe.")
    if not is_backend_compatible_email(email):
        raise ExecutableProfileError(
            f"{field}.email is not accepted by the backend email contract."
        )
    boolean_fields = (
        "enabled",
        "emailVerified",
        "temporaryPassword",
        "productionCleanupRequired",
    )
    invalid = [
        name for name in boolean_fields if not isinstance(user[name], bool)
    ]
    if invalid:
        raise ExecutableProfileError(f"{field}.{invalid[0]} must be boolean.")
    if user["productionCleanupRequired"] is not True:
        raise ExecutableProfileError(
            "Every bootstrap test user must require production cleanup."
        )
    return username, email


def _validate_test_user_roles(
    user: Mapping[str, object],
    index: int,
    realm_roles: set[str],
) -> None:
    """Validate one test user's exact application-role references.

    Args:
        user: Secret-free test-user mapping.
        index: Position used in precise validation errors.
        realm_roles: Declared application realm-role names.

    Raises:
        ExecutableProfileError: If assignments are empty, duplicated, or
            reference undeclared roles.
    """

    field = f"auth.bootstrapTestUsers[{index}].realmRoles"
    assigned = [
        text(value, f"{field}[{role_index}]")
        for role_index, value in enumerate(
            sequence(user["realmRoles"], field)
        )
    ]
    if not assigned or len(assigned) != len(set(assigned)):
        raise ExecutableProfileError(
            "Bootstrap test-user realm roles must be non-empty and unique."
        )
    unknown = sorted(set(assigned) - realm_roles)
    if unknown:
        raise ExecutableProfileError(
            "Bootstrap test users reference undeclared realm roles: "
            + ", ".join(unknown)
        )


def _validate_bootstrap_test_user(
    raw_user: object,
    index: int,
    realm_roles: set[str],
) -> tuple[str, str]:
    """Validate one complete secret-free bootstrap test-user declaration.

    Args:
        raw_user: Parsed candidate declaration.
        index: Position used in precise validation errors.
        realm_roles: Declared application realm-role names.

    Returns:
        Validated username and email.

    Raises:
        ExecutableProfileError: If the declaration is malformed or unsafe.
    """

    field = f"auth.bootstrapTestUsers[{index}]"
    user = mapping(raw_user, field)
    required = {
        "username",
        "email",
        "firstName",
        "lastName",
        "enabled",
        "emailVerified",
        "temporaryPassword",
        "realmRoles",
        "productionCleanupRequired",
    }
    require_keys(user, required, field)
    unsupported = sorted(set(user) - required)
    if unsupported:
        raise ExecutableProfileError(
            f"{field} contains unsupported fields: "
            + ", ".join(unsupported)
        )
    identity = _validate_test_user_identity(user, index)
    _validate_test_user_roles(user, index, realm_roles)
    return identity


def _validate_bootstrap_test_users(
    auth: Mapping[str, object],
    realm_roles: set[str],
    forbidden_usernames: set[str],
) -> None:
    """Validate all secret-free test-user identities and uniqueness rules.

    Args:
        auth: Profile authentication mapping.
        realm_roles: Validated application realm-role names.
        forbidden_usernames: Explicitly forbidden default usernames.

    Raises:
        ExecutableProfileError: If declarations or aggregate policy are unsafe.
    """

    enabled = auth["bootstrapTestUsersEnabled"]
    if not isinstance(enabled, bool):
        raise ExecutableProfileError(
            "auth.bootstrapTestUsersEnabled must be boolean."
        )
    identities = [
        _validate_bootstrap_test_user(raw_user, index, realm_roles)
        for index, raw_user in enumerate(
            sequence(auth["bootstrapTestUsers"], "auth.bootstrapTestUsers")
        )
    ]
    usernames = [username for username, _ in identities]
    emails = [email for _, email in identities]
    if enabled and not usernames:
        raise ExecutableProfileError(
            "Enabled bootstrap test users require at least one declaration."
        )
    if len(usernames) != len(set(usernames)):
        raise ExecutableProfileError(
            "auth.bootstrapTestUsers usernames must be unique."
        )
    if len(emails) != len(set(emails)):
        raise ExecutableProfileError(
            "auth.bootstrapTestUsers emails must be unique."
        )
    overlap = sorted(set(usernames) & forbidden_usernames)
    if overlap:
        raise ExecutableProfileError(
            "Bootstrap test users cannot also be forbidden: "
            + ", ".join(overlap)
        )


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
    realm_roles = _validate_realm_roles(auth)
    _validate_bootstrap_test_users(auth, realm_roles, set(forbidden))


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

    require_keys(auth, KEYCLOAK_AUTH_REQUIRED_FIELDS, "auth")
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
