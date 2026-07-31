"""
Module: executable_profile_deployment_validation.py

Description:
    Validates operator-owned root environment values against the selected
    tracked executable profile. Application and authentication identity cannot
    be overridden, while stack names, routing, images, ports, resources,
    storage, and database mode are validated before rendering or mutation.

Dependencies:
    - Python standard library.
    - scripts/executable_profile_config_validation.py.
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
from executable_profile_support import (
    IMAGE_PATTERN,
    MEMORY_PATTERN,
    NAME_PATTERN,
    SEMVER_PATTERN,
    ExecutableProfileError,
    fixed_deployment_values,
    mapping,
    sequence,
)


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
        if not MEMORY_PATTERN.fullmatch(values[key]):
            raise ExecutableProfileError(
                f".env {key} is not a safe memory limit."
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

    for key, expected in fixed_deployment_values(data, config_id).items():
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
    _validate_counts_and_resources(values)
    _validate_data_root(values)
    _validate_proxy(values)
    _validate_database(data, values)
    _validate_web(data, values)


__all__ = ["validate_deployment"]
