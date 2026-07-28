"""
Module: executable_profile_config_validation.py

Description:
    Validates tracked schema-5 executable site configuration. The module
    enforces safe public URLs, exact Keycloak identity, service consistency,
    immutable image declarations, and secret identifier boundaries without
    containing any application-specific values.

Dependencies:
    - Python standard library.
    - scripts/executable_profile_support.py.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Mapping
from urllib.parse import urlparse

from executable_profile_support import (
    DIGEST_IMAGE_PATTERN,
    IMAGE_PATTERN,
    NAME_PATTERN,
    SECRET_PATTERN,
    SEMVER_PATTERN,
    ExecutableProfileError,
    mapping,
    require_keys,
    sequence,
    text,
)


def validate_https(value: str, field: str) -> None:
    """Require one non-local absolute HTTPS URL.

    Args:
        value: Candidate URL.
        field: Diagnostic field name.

    Raises:
        ExecutableProfileError: If the URL is unsafe for production.
    """

    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ExecutableProfileError(f"{field} must be an absolute HTTPS URL.")
    if parsed.username or parsed.password:
        raise ExecutableProfileError(f"{field} must not contain credentials.")
    if parsed.query or parsed.fragment:
        raise ExecutableProfileError(
            f"{field} must not contain query or fragment."
        )
    hostname = parsed.hostname.lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ExecutableProfileError(f"{field} must not use a local host.")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
    ):
        raise ExecutableProfileError(
            f"{field} must not use a private or non-routable address."
        )
    if "*" in value or ".invalid" in value:
        raise ExecutableProfileError(f"{field} must not contain placeholders.")


def validate_origin(value: str, field: str) -> None:
    """Require one exact HTTPS origin without a path.

    Args:
        value: Candidate browser origin.
        field: Diagnostic field name.

    Raises:
        ExecutableProfileError: If the value is not an exact public origin.
    """

    validate_https(value, field)
    if urlparse(value).path not in {"", "/"}:
        raise ExecutableProfileError(f"{field} must not contain a path.")


def validate_domain(value: object, field: str, base_url: str) -> None:
    """Require a plain public hostname matching its declared base URL.

    Args:
        value: Candidate domain field.
        field: Diagnostic field name.
        base_url: Validated public base URL.

    Raises:
        ExecutableProfileError: If the hostname is malformed or drifts.
    """

    domain = text(value, field)
    hostname = urlparse(base_url).hostname
    if (
        hostname is None
        or "://" in domain
        or "/" in domain
        or "*" in domain
        or domain.lower() != hostname.lower()
    ):
        raise ExecutableProfileError(
            f"{field} must be the hostname from its public base URL."
        )


def validate_port(value: object, field: str) -> None:
    """Require one TCP port in the inclusive range 1 through 65535.

    Args:
        value: Candidate numeric value.
        field: Diagnostic field name.

    Raises:
        ExecutableProfileError: If the value is not a valid TCP port.
    """

    if isinstance(value, bool):
        raise ExecutableProfileError(f"{field} must be a TCP port.")
    try:
        port = int(str(value))
    except ValueError as error:
        raise ExecutableProfileError(f"{field} must be a TCP port.") from error
    if port < 1 or port > 65535:
        raise ExecutableProfileError(f"{field} must be between 1 and 65535.")


def _validate_redirect_uri(value: str, field: str) -> None:
    """Validate one exact Web or custom-scheme OIDC callback.

    Args:
        value: Candidate redirect URI.
        field: Diagnostic field name.

    Raises:
        ExecutableProfileError: If the callback is broad, local, or malformed.
    """

    if "*" in value or ".invalid" in value:
        raise ExecutableProfileError(
            f"{field} must be exact and non-placeholder."
        )
    parsed = urlparse(value)
    if parsed.scheme == "https":
        validate_https(value, field)
        return
    if (
        not re.fullmatch(r"[a-z][a-z0-9+.-]*", parsed.scheme)
        or parsed.scheme in {"http", "file"}
        or not parsed.path.startswith("/")
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ExecutableProfileError(
            f"{field} must be HTTPS or an exact custom-scheme callback."
        )


def _validate_release_image(
    image: Mapping[str, object],
    field: str,
) -> None:
    """Validate one immutable-version release image declaration.

    Args:
        image: Image mapping.
        field: Diagnostic field name.

    Raises:
        ExecutableProfileError: If repository or version policy is unsafe.
    """

    require_keys(
        image,
        {"name", "defaultVersion", "mutableTagsAllowed"},
        field,
    )
    name = text(image["name"], f"{field}.name")
    version = text(image["defaultVersion"], f"{field}.defaultVersion")
    if not IMAGE_PATTERN.fullmatch(name) or "/" not in name:
        raise ExecutableProfileError(
            f"{field}.name must be a registry repository."
        )
    if not SEMVER_PATTERN.fullmatch(version):
        raise ExecutableProfileError(
            f"{field}.defaultVersion must be semantic version."
        )
    if image["mutableTagsAllowed"] is not False:
        raise ExecutableProfileError(
            f"{field}.mutableTagsAllowed must be false."
        )


def _validate_database(
    data: Mapping[str, object],
    services: Mapping[str, object],
) -> None:
    """Validate database service declarations and pinned images.

    Args:
        data: Full site profile.
        services: Validated services mapping.

    Raises:
        ExecutableProfileError: If database type, mode, or image drifts.
    """

    database = mapping(data["database"], "database")
    require_keys(
        database,
        {"type", "defaultMode", "allowedModes"},
        "database",
    )
    database_type = text(database["type"], "database.type")
    allowed_modes = {
        text(mode, f"database.allowedModes[{index}]")
        for index, mode in enumerate(
            sequence(database["allowedModes"], "database.allowedModes")
        )
    }
    if database_type == "none":
        if services.get("database") is True or allowed_modes != {"none"}:
            raise ExecutableProfileError(
                "database.type=none requires services.database=false and mode none."
            )
    elif database_type == "postgresql":
        if services.get("database") is not True:
            raise ExecutableProfileError(
                "PostgreSQL profiles require services.database=true."
            )
        if not allowed_modes or not allowed_modes <= {"local", "external"}:
            raise ExecutableProfileError(
                "PostgreSQL modes must be local and/or external."
            )
    else:
        raise ExecutableProfileError(
            "Executable profiles currently support postgresql or none."
        )
    if database["defaultMode"] not in sequence(
        database["allowedModes"],
        "database.allowedModes",
    ):
        raise ExecutableProfileError("database.defaultMode must be allowed.")
    for field in ("image", "pgadminImage"):
        if field in database and not DIGEST_IMAGE_PATTERN.fullmatch(
            text(database[field], f"database.{field}")
        ):
            raise ExecutableProfileError(
                f"database.{field} must be digest-pinned."
            )
    if "redisImage" in services and not DIGEST_IMAGE_PATTERN.fullmatch(
        text(services["redisImage"], "services.redisImage")
    ):
        raise ExecutableProfileError(
            "services.redisImage must be digest-pinned."
        )


def _validate_secret_declarations(data: Mapping[str, object]) -> None:
    """Validate required, optional, and base-mounted secret identifiers.

    Args:
        data: Site profile containing identifier-only secret declarations.

    Raises:
        ExecutableProfileError: If names overlap, drift, or are unsafe.
    """

    required = [
        text(value, f"secrets[{index}]")
        for index, value in enumerate(sequence(data["secrets"], "secrets"))
    ]
    optional = [
        text(value, f"optionalSecrets[{index}]")
        for index, value in enumerate(
            sequence(data.get("optionalSecrets", []), "optionalSecrets")
        )
    ]
    if any(not SECRET_PATTERN.fullmatch(value) for value in required + optional):
        raise ExecutableProfileError("Docker secret identifiers are unsafe.")
    if (
        len(required) != len(set(required))
        or len(optional) != len(set(optional))
        or set(required) & set(optional)
    ):
        raise ExecutableProfileError(
            "Required and optional Docker secret identifiers must be unique."
        )
    mounted_names = [
        text(
            mapping(raw_mount, f"secretMounts[{index}]").get("name"),
            f"secretMounts[{index}].name",
        )
        for index, raw_mount in enumerate(
            sequence(data["secretMounts"], "secretMounts")
        )
    ]
    if set(mounted_names) - set(required):
        raise ExecutableProfileError(
            "Base secret mounts must be declared in required secrets."
        )


def _validate_protected_identity(
    auth: Mapping[str, object],
    realm: str,
) -> None:
    """Reject target identity intersecting profile-protected legacy data.

    Args:
        auth: Validated Keycloak mapping.
        realm: Candidate realm.

    Raises:
        ExecutableProfileError: If realm, clients, or origins intersect.
    """

    protected = mapping(
        auth.get("protectedIdentity", {}),
        "auth.protectedIdentity",
    )
    protected_realms = {
        text(value, f"auth.protectedIdentity.realms[{index}]")
        for index, value in enumerate(
            sequence(
                protected.get("realms", []),
                "auth.protectedIdentity.realms",
            )
        )
    }
    protected_clients = {
        text(value, f"auth.protectedIdentity.clientIds[{index}]")
        for index, value in enumerate(
            sequence(
                protected.get("clientIds", []),
                "auth.protectedIdentity.clientIds",
            )
        )
    }
    protected_origins = {
        text(value, f"auth.protectedIdentity.origins[{index}]")
        for index, value in enumerate(
            sequence(
                protected.get("origins", []),
                "auth.protectedIdentity.origins",
            )
        )
    }
    for index, origin in enumerate(sorted(protected_origins)):
        validate_origin(
            origin,
            f"auth.protectedIdentity.origins[{index}]",
        )
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


def _validate_keycloak_auth(auth: Mapping[str, object]) -> None:
    """Validate generic Keycloak realm/client/bootstrap metadata.

    Args:
        auth: Profile authentication mapping.

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
            "frontendClientId",
            "audience",
            "adminClientId",
            "redirectUris",
            "webOrigins",
        },
        "auth",
    )
    for field in ("serverUrl", "issuerUrl", "jwksUrl"):
        validate_https(text(auth[field], f"auth.{field}"), f"auth.{field}")
    realm = text(auth["realm"], "auth.realm")
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
    for field in ("frontendClientId", "audience", "adminClientId"):
        if not NAME_PATTERN.fullmatch(text(auth[field], f"auth.{field}")):
            raise ExecutableProfileError(f"auth.{field} is unsafe.")
    redirects = sequence(auth["redirectUris"], "auth.redirectUris")
    if not redirects:
        raise ExecutableProfileError("auth.redirectUris must not be empty.")
    for index, redirect_uri in enumerate(redirects):
        _validate_redirect_uri(
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
    _validate_protected_identity(auth, realm)
    _validate_service_account_roles(auth)


def _validate_routing(
    data: Mapping[str, object],
    services: Mapping[str, object],
) -> None:
    """Validate API and optional WebApp public routing declarations.

    Args:
        data: Full site profile.
        services: Validated services mapping.

    Raises:
        ExecutableProfileError: If routes, ports, or images are unsafe.
    """

    routing = mapping(data["routing"], "routing")
    require_keys(
        routing,
        {"containerPort", "apiBaseUrl", "domain", "healthPath"},
        "routing",
    )
    api_url = text(routing["apiBaseUrl"], "routing.apiBaseUrl")
    validate_https(api_url, "routing.apiBaseUrl")
    validate_domain(routing["domain"], "routing.domain", api_url)
    validate_port(routing["containerPort"], "routing.containerPort")
    health_path = text(routing["healthPath"], "routing.healthPath")
    if not health_path.startswith("/") or health_path.startswith("/api/"):
        raise ExecutableProfileError(
            "routing.healthPath must be a relative API-service route."
        )
    if services.get("web") is not True:
        return
    required = (
        "webBaseUrl",
        "webDomain",
        "webContainerPort",
        "webHealthPath",
    )
    for field in required:
        if field not in routing:
            raise ExecutableProfileError(
                f"routing.{field} is required for WebApp."
            )
    web_url = text(routing["webBaseUrl"], "routing.webBaseUrl")
    validate_https(web_url, "routing.webBaseUrl")
    validate_domain(routing["webDomain"], "routing.webDomain", web_url)
    validate_port(routing["webContainerPort"], "routing.webContainerPort")
    if not text(
        routing["webHealthPath"],
        "routing.webHealthPath",
    ).startswith("/"):
        raise ExecutableProfileError(
            "routing.webHealthPath must begin with '/'."
        )
    web = mapping(data.get("web"), "web")
    require_keys(web, {"image", "resources"}, "web")
    _validate_release_image(mapping(web["image"], "web.image"), "web.image")


def validate_config(data: Mapping[str, object]) -> None:
    """Validate the reusable executable site-config contract.

    Args:
        data: Parsed profile.

    Raises:
        ExecutableProfileError: If required sections or public values are unsafe.
    """

    require_keys(
        data,
        {
            "version",
            "appId",
            "name",
            "renderer",
            "stack",
            "exposure",
            "routing",
            "database",
            "services",
            "image",
            "resources",
            "storage",
            "cors",
            "environment",
            "envKeys",
            "secrets",
            "secretMounts",
            "health",
        },
        "profile",
    )
    if str(data["version"]) != "5.0":
        raise ExecutableProfileError(
            "Executable site profiles require version 5.0."
        )
    renderer = mapping(data["renderer"], "renderer")
    if renderer.get("type") != "executable" or renderer.get("strict") is not True:
        raise ExecutableProfileError(
            "Executable profiles require renderer.type=executable and strict=true."
        )
    if not NAME_PATTERN.fullmatch(text(data["appId"], "appId")):
        raise ExecutableProfileError("appId is unsafe.")
    stack = mapping(data["stack"], "stack")
    require_keys(
        stack,
        {"family", "role", "primaryService", "name"},
        "stack",
    )
    if not NAME_PATTERN.fullmatch(text(stack["name"], "stack.name")):
        raise ExecutableProfileError("stack.name is unsafe.")
    services = mapping(data["services"], "services")
    if services.get("api") is not True:
        raise ExecutableProfileError(
            "Executable API profiles require services.api=true."
        )
    _validate_routing(data, services)
    _validate_release_image(mapping(data["image"], "image"), "image")
    _validate_database(data, services)
    cors = mapping(data["cors"], "cors")
    for index, origin in enumerate(sequence(cors["origins"], "cors.origins")):
        validate_origin(
            text(origin, f"cors.origins[{index}]"),
            f"cors.origins[{index}]",
        )
    _validate_secret_declarations(data)
    auth = mapping(data.get("auth", {"provider": "none"}), "auth")
    if auth.get("provider") == "keycloak":
        _validate_keycloak_auth(auth)


__all__ = [
    "validate_config",
    "validate_domain",
    "validate_https",
    "validate_origin",
    "validate_port",
]
