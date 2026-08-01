"""
Module: executable_profile_deployment_validation.py

Description:
    Validates operator-owned root environment values against the selected
    tracked executable profile. Application/service identity and the Keycloak
    credential destination remain fixed, while routing, images, Keycloak realm
    and client identity, resources, and database mode are validated before
    rendering or mutation.

Dependencies:
    - Python standard library.
    - scripts/executable_profile_config_validation.py.
    - scripts/executable_profile_keycloak_validation.py.
    - scripts/executable_profile_support.py.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from executable_profile_config_validation import (
    validate_domain,
    validate_https,
    validate_origin,
    validate_port,
)
from executable_profile_keycloak_validation import (
    KEYCLOAK_RESERVED_MANAGED_CLIENT_IDS,
)
from executable_profile_support import (
    IMAGE_PATTERN,
    MEMORY_PATTERN,
    NAME_PATTERN,
    SEMVER_PATTERN,
    ExecutableProfileError,
    KEYCLOAK_REALM_SETTING_ENV_KEYS,
    immutable_deployment_values,
    mapping,
    memory_limit_is_unlimited,
    sequence,
    text,
)


def _validate_keycloak_boolean_values(
    values: Mapping[str, str],
) -> None:
    """Validate editable realm and test-user toggle values.

    Empty values are accepted only as a migration bridge for root ``.env``
    files generated before these public settings became editable. The active
    identity then falls back to the tracked profile default, and the next
    guided bootstrap writes explicit values.

    Args:
        values: Complete generated deployment environment.

    Raises:
        ExecutableProfileError: If a populated toggle is not boolean text.
    """

    keys = [
        *(key for _, key in KEYCLOAK_REALM_SETTING_ENV_KEYS),
        "KEYCLOAK_BOOTSTRAP_TEST_USERS_ENABLED",
    ]
    for key in keys:
        if values[key] not in {"", "true", "false"}:
            raise ExecutableProfileError(
                f".env {key} must be true or false."
            )


def _protected_auth_values(
    auth: Mapping[str, object],
    key: str,
) -> set[str]:
    """Return one normalized protected Keycloak identity set.

    Args:
        auth: Tracked profile authentication mapping.
        key: Protected identity array name.

    Returns:
        Protected string values declared for the selected profile.
    """

    protected = mapping(
        auth.get("protectedIdentity", {}),
        "auth.protectedIdentity",
    )
    return {
        str(value)
        for value in sequence(
            protected.get(key, []),
            f"auth.protectedIdentity.{key}",
        )
    }


def _validate_keycloak_client_values(
    auth: Mapping[str, object],
    values: Mapping[str, str],
) -> None:
    """Validate editable client IDs and protected-client boundaries.

    Args:
        auth: Tracked profile authentication mapping.
        values: Complete generated deployment environment.

    Raises:
        ExecutableProfileError: If clients are malformed, equal, reserved, or
            protected as legacy identity.
    """

    client_keys = (
        "KEYCLOAK_FRONTEND_CLIENT_ID",
        "KEYCLOAK_BACKEND_CLIENT_ID",
        "KEYCLOAK_AUDIENCE",
    )
    for key in client_keys:
        if not NAME_PATTERN.fullmatch(values[key]):
            raise ExecutableProfileError(f".env {key} is unsafe.")
    managed_clients = {
        values["KEYCLOAK_FRONTEND_CLIENT_ID"],
        values["KEYCLOAK_BACKEND_CLIENT_ID"],
    }
    if len(managed_clients) != 2:
        raise ExecutableProfileError(
            "Keycloak frontend and backend client IDs must differ."
        )
    if managed_clients & KEYCLOAK_RESERVED_MANAGED_CLIENT_IDS:
        raise ExecutableProfileError(
            "Managed Keycloak client IDs must not use built-in clients."
        )
    candidates = managed_clients | {values["KEYCLOAK_AUDIENCE"]}
    if candidates & _protected_auth_values(auth, "clientIds"):
        raise ExecutableProfileError(
            "Keycloak deployment identity intersects protected clients."
        )


def _validate_keycloak_deployment(
    data: Mapping[str, object],
    values: Mapping[str, str],
) -> None:
    """Validate editable Keycloak identity against profile safety policy.

    Args:
        data: Tracked executable profile.
        values: Complete generated deployment environment.

    Raises:
        ExecutableProfileError: If an identity value is malformed,
            inconsistent, reserved, or protected as legacy state.
    """

    auth = mapping(data.get("auth", {"provider": "none"}), "auth")
    keycloak_keys = (
        "KEYCLOAK_BASE_URL",
        "KEYCLOAK_ISSUER_URL",
        "KEYCLOAK_REALM",
        "KEYCLOAK_REALM_DISPLAY_NAME",
        *(key for _, key in KEYCLOAK_REALM_SETTING_ENV_KEYS),
        "KEYCLOAK_BOOTSTRAP_TEST_USERS_ENABLED",
        "KEYCLOAK_AUDIENCE",
        "KEYCLOAK_FRONTEND_CLIENT_ID",
        "KEYCLOAK_BACKEND_CLIENT_ID",
    )
    if values["AUTH_PROVIDER"] != "keycloak":
        if any(values[key] for key in keycloak_keys):
            raise ExecutableProfileError(
                "Non-Keycloak deployments must not declare Keycloak identity."
            )
        return
    _validate_keycloak_boolean_values(values)
    base_url = values["KEYCLOAK_BASE_URL"].rstrip("/")
    realm = values["KEYCLOAK_REALM"]
    validate_origin(base_url, ".env KEYCLOAK_BASE_URL")
    if not NAME_PATTERN.fullmatch(realm) or realm == "master":
        raise ExecutableProfileError(".env KEYCLOAK_REALM is unsafe.")
    expected_issuer = f"{base_url}/realms/{realm}"
    if values["KEYCLOAK_ISSUER_URL"].rstrip("/") != expected_issuer:
        raise ExecutableProfileError(
            ".env KEYCLOAK_ISSUER_URL must match base URL and realm."
        )
    validate_https(expected_issuer, ".env KEYCLOAK_ISSUER_URL")
    display_name = values["KEYCLOAK_REALM_DISPLAY_NAME"] or str(
        auth["realmDisplayName"]
    )
    if len(text(display_name, ".env KEYCLOAK_REALM_DISPLAY_NAME")) > 128:
        raise ExecutableProfileError(
            ".env KEYCLOAK_REALM_DISPLAY_NAME is too long."
        )
    if realm in _protected_auth_values(auth, "realms"):
        raise ExecutableProfileError(
            ".env KEYCLOAK_REALM must not target a protected realm."
        )
    _validate_keycloak_client_values(auth, values)


def _validate_operator_identity(
    data: Mapping[str, object],
    values: Mapping[str, str],
) -> None:
    """Validate operator-selected stack, routes, CORS, and image repositories.

    Args:
        data: Tracked executable profile.
        values: Complete generated deployment environment.

    Raises:
        ExecutableProfileError: If a deployment identity value is unsafe,
            internally inconsistent, or intersects protected legacy origins.
    """

    if not NAME_PATTERN.fullmatch(values["STACK_NAME"]):
        raise ExecutableProfileError(".env STACK_NAME is unsafe.")
    validate_https(values["API_BASE_URL"], ".env API_BASE_URL")
    validate_domain(
        values["DOMAIN"],
        ".env DOMAIN",
        values["API_BASE_URL"],
    )
    for key in ("IMAGE_NAME", "WEB_IMAGE_NAME"):
        if values[key] and not IMAGE_PATTERN.fullmatch(values[key]):
            raise ExecutableProfileError(f".env {key} is unsafe.")

    web_enabled = values["WEB_ENABLED"] == "true"
    if web_enabled:
        validate_origin(values["WEB_BASE_URL"], ".env WEB_BASE_URL")
        validate_domain(
            values["WEB_DOMAIN"],
            ".env WEB_DOMAIN",
            values["WEB_BASE_URL"],
        )
    elif values["WEB_BASE_URL"] or values["WEB_DOMAIN"]:
        raise ExecutableProfileError(
            "Web-disabled profiles must not declare WebApp routing."
        )

    origins = {
        origin.strip()
        for origin in values["CORS_ORIGINS"].split(",")
        if origin.strip()
    }
    if not origins:
        raise ExecutableProfileError(".env CORS_ORIGINS must not be empty.")
    for index, origin in enumerate(sorted(origins)):
        validate_origin(origin, f".env CORS_ORIGINS[{index}]")
    if web_enabled and values["WEB_BASE_URL"] not in origins:
        raise ExecutableProfileError(
            ".env CORS_ORIGINS must include the active WebApp origin."
        )

    auth = mapping(data.get("auth", {"provider": "none"}), "auth")
    protected = mapping(
        auth.get("protectedIdentity", {}),
        "auth.protectedIdentity",
    )
    protected_origins = {
        str(origin)
        for origin in sequence(
            protected.get("origins", []),
            "auth.protectedIdentity.origins",
        )
    }
    if values["WEB_BASE_URL"] in protected_origins:
        raise ExecutableProfileError(
            ".env WEB_BASE_URL must not target a protected legacy origin."
        )


def _validate_counts_and_resources(values: Mapping[str, str]) -> None:
    """Validate replicas and memory limits.

    Args:
        values: Complete generated deployment environment.

    Raises:
        ExecutableProfileError: If a resource value is unsafe.
    """

    for key in ("API_REPLICAS", "WEB_REPLICAS", "PGADMIN_REPLICAS"):
        if not values[key].isdigit():
            raise ExecutableProfileError(
                f".env {key} must be a non-negative integer."
            )
    if int(values["API_REPLICAS"]) < 1:
        raise ExecutableProfileError(".env API_REPLICAS must be at least 1.")
    if values["WEB_ENABLED"] == "true" and int(values["WEB_REPLICAS"]) < 1:
        raise ExecutableProfileError(".env WEB_REPLICAS must be at least 1.")
    for key in ("MEMORY_LIMIT", "WEB_MEMORY_LIMIT"):
        if not memory_limit_is_unlimited(
            values[key]
        ) and not MEMORY_PATTERN.fullmatch(values[key]):
            raise ExecutableProfileError(
                f".env {key} must be unlimited, 0, or a safe byte quantity."
            )


def _validate_data_root(values: Mapping[str, str]) -> None:
    """Require one safe absolute POSIX or Windows host storage path.

    Args:
        values: Complete generated deployment environment.

    Raises:
        ExecutableProfileError: If ``DATA_ROOT`` is broad or malformed.
    """

    data_root = values["DATA_ROOT"]
    posix_path = PurePosixPath(data_root)
    native_path = Path(data_root)
    posix_safe = bool(re.fullmatch(r"/[A-Za-z0-9._/-]+", data_root))
    windows_safe = bool(
        re.fullmatch(r"[A-Za-z]:[\\/][A-Za-z0-9._/\\ -]+", data_root)
    )
    path_parts = tuple(part for part in re.split(r"[\\/]", data_root) if part)
    if (
        not (
            (posix_path.is_absolute() and posix_safe)
            or (native_path.is_absolute() and windows_safe)
        )
        or data_root in {"/", "\\"}
        or ".." in path_parts
        or "//" in data_root
        or "\\\\" in data_root
    ):
        raise ExecutableProfileError(
            ".env DATA_ROOT must be a specific absolute host path."
        )


def _validate_proxy(values: Mapping[str, str]) -> None:
    """Validate proxy/TLS ownership and all direct published ports.

    Args:
        values: Complete generated deployment environment.

    Raises:
        ExecutableProfileError: If proxy mode, resolver, network, provider
            constraint, or port fails.
    """

    if values["PROXY_TYPE"] not in {"traefik", "none"}:
        raise ExecutableProfileError(
            ".env PROXY_TYPE must be traefik or none."
        )
    if values["PROXY_TYPE"] == "none":
        if (
            values["SSL_MODE"]
            or values["TRAEFIK_NETWORK"]
            or values["TRAEFIK_CONSTRAINT_LABEL"]
        ):
            raise ExecutableProfileError(
                "Direct-port mode must not declare Traefik TLS, network, "
                "or provider-constraint state."
            )
    else:
        if values["SSL_MODE"] not in {"letsencrypt", "proxy"}:
            raise ExecutableProfileError(
                "Traefik mode requires letsencrypt or proxy TLS ownership."
            )
        if not NAME_PATTERN.fullmatch(values["TRAEFIK_NETWORK"]):
            raise ExecutableProfileError(
                ".env TRAEFIK_NETWORK is required and must be safe."
            )
        if not NAME_PATTERN.fullmatch(
            values["TRAEFIK_CONSTRAINT_LABEL"]
        ):
            raise ExecutableProfileError(
                ".env TRAEFIK_CONSTRAINT_LABEL is required and must be safe."
            )
    if values["SSL_MODE"] == "letsencrypt" and not NAME_PATTERN.fullmatch(
        values["TRAEFIK_CERT_RESOLVER"]
    ):
        raise ExecutableProfileError(
            ".env TRAEFIK_CERT_RESOLVER is required for letsencrypt."
        )
    for key in (
        "API_PUBLISHED_PORT",
        "WEB_PUBLISHED_PORT",
        "PGADMIN_PUBLISHED_PORT",
    ):
        validate_port(values[key], f".env {key}")


def _validate_database(
    data: Mapping[str, object],
    values: Mapping[str, str],
) -> None:
    """Validate selected database mode and optional pgAdmin.

    Args:
        data: Tracked executable profile.
        values: Complete generated deployment environment.

    Raises:
        ExecutableProfileError: If mode, host, port, or pgAdmin is inconsistent.
    """

    database = mapping(data["database"], "database")
    allowed_modes = {
        str(item)
        for item in sequence(
            database["allowedModes"],
            "database.allowedModes",
        )
    }
    if values["DB_MODE"] not in allowed_modes:
        raise ExecutableProfileError(
            ".env DB_MODE is not allowed by the profile."
        )
    validate_port(values["DB_PORT"], ".env DB_PORT")
    database_type = str(database["type"])
    if values["DB_HOST"] and (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", values["DB_HOST"])
        or ".." in values["DB_HOST"]
    ):
        raise ExecutableProfileError(".env DB_HOST is unsafe.")
    for key in ("DB_NAME", "DB_USER"):
        if values[key] and not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]*",
            values[key],
        ):
            raise ExecutableProfileError(f".env {key} is unsafe.")
    if database_type == "none":
        if values["DB_MODE"] != "none" or values["PGADMIN_ENABLED"] != "false":
            raise ExecutableProfileError(
                "Database-free profiles require DB_MODE=none and no pgAdmin."
            )
        return
    if values["DB_MODE"] == "local":
        expected_host = str(
            mapping(data["environment"], "environment").get(
                "DB_HOST",
                "postgres",
            )
        )
        if values["DB_HOST"] != expected_host:
            raise ExecutableProfileError(
                ".env DB_HOST must use the profile's local database service."
            )
    elif values["DB_MODE"] == "external":
        external_host = values["DB_HOST"].lower()
        if (
            not external_host
            or external_host == "localhost"
            or external_host.endswith(".localhost")
            or external_host in {"127.0.0.1", "::1", "postgres"}
        ):
            raise ExecutableProfileError(
                ".env DB_HOST must identify the external database."
            )
    if values["PGADMIN_ENABLED"] != "true":
        return
    if database_type != "postgresql" or values["DB_MODE"] != "local":
        raise ExecutableProfileError(
            "pgAdmin requires a local PostgreSQL service."
        )
    if int(values["PGADMIN_REPLICAS"]) < 1:
        raise ExecutableProfileError(
            ".env PGADMIN_REPLICAS must be at least 1 when enabled."
        )
    validate_domain(
        values["PGADMIN_DOMAIN"],
        ".env PGADMIN_DOMAIN",
        f"https://{values['PGADMIN_DOMAIN']}",
    )
    if not re.fullmatch(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}",
        values["PGADMIN_EMAIL"],
    ):
        raise ExecutableProfileError(
            ".env PGADMIN_EMAIL must be a non-empty email address."
        )


def _validate_web(
    data: Mapping[str, object],
    values: Mapping[str, str],
) -> None:
    """Validate optional WebApp enablement.

    Args:
        data: Tracked executable profile.
        values: Complete generated deployment environment.

    Raises:
        ExecutableProfileError: If WebApp state drifts from site config.
    """

    expected_enabled = str(
        bool(mapping(data["services"], "services").get("web", False))
    ).lower()
    if values["WEB_ENABLED"] != expected_enabled:
        raise ExecutableProfileError(
            ".env WEB_ENABLED must match services.web."
        )
    if values["WEB_ENABLED"] != "true":
        return


def validate_deployment(
    data: Mapping[str, object],
    config_id: str,
    values: Mapping[str, str],
) -> None:
    """Validate generated deployment values against selected site config.

    Args:
        data: Parsed executable profile.
        config_id: Selected profile ID.
        values: Root environment values.

    Raises:
        ExecutableProfileError: If fixed identity or operator values drift.
    """

    for key, expected in immutable_deployment_values(data, config_id).items():
        if values[key] != expected:
            raise ExecutableProfileError(
                f".env {key} must match site-config value {expected!r}."
            )
    for key in ("IMAGE_VERSION", "WEB_IMAGE_VERSION"):
        if values[key] and not SEMVER_PATTERN.fullmatch(values[key]):
            raise ExecutableProfileError(
                f".env {key} must be semantic version."
            )
    if values["PGADMIN_ENABLED"] not in {"true", "false"}:
        raise ExecutableProfileError(
            ".env PGADMIN_ENABLED must be true or false."
        )
    _validate_operator_identity(data, values)
    _validate_keycloak_deployment(data, values)
    _validate_counts_and_resources(values)
    _validate_data_root(values)
    _validate_proxy(values)
    _validate_database(data, values)
    _validate_web(data, values)


__all__ = ["validate_deployment"]
