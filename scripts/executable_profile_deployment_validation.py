"""
Module: executable_profile_deployment_validation.py

Description:
    Validates operator-owned root environment values against the selected
    tracked executable profile. Fixed identity cannot be overridden, while
    ports, proxy settings, resources, storage, and database mode are checked
    before rendering or mutation.

Dependencies:
    - Python standard library.
    - scripts/executable_profile_config_validation.py.
    - scripts/executable_profile_support.py.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePosixPath

from executable_profile_config_validation import (
    validate_domain,
    validate_port,
)
from executable_profile_support import (
    MEMORY_PATTERN,
    NAME_PATTERN,
    SEMVER_PATTERN,
    ExecutableProfileError,
    fixed_deployment_values,
    mapping,
    sequence,
)


def _validate_counts_and_resources(values: Mapping[str, str]) -> None:
    """Validate replicas, memory limits, and data root.

    Args:
        values: Complete generated deployment environment.

    Raises:
        ExecutableProfileError: If a resource or storage value is unsafe.
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
    data_root = PurePosixPath(values["DATA_ROOT"])
    if (
        not data_root.is_absolute()
        or values["DATA_ROOT"] in {"/", "\\"}
        or ".." in data_root.parts
    ):
        raise ExecutableProfileError(
            ".env DATA_ROOT must be a specific absolute host path."
        )


def _validate_proxy(values: Mapping[str, str]) -> None:
    """Validate proxy/TLS ownership and all direct published ports.

    Args:
        values: Complete generated deployment environment.

    Raises:
        ExecutableProfileError: If proxy mode, resolver, network, or port fails.
    """

    if values["PROXY_TYPE"] not in {"traefik", "none"}:
        raise ExecutableProfileError(
            ".env PROXY_TYPE must be traefik or none."
        )
    if values["PROXY_TYPE"] == "none":
        if values["SSL_MODE"] or values["TRAEFIK_NETWORK"]:
            raise ExecutableProfileError(
                "Direct-port mode must not declare Traefik TLS or network state."
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
    if (
        "@" not in values["PGADMIN_EMAIL"]
        or values["PGADMIN_EMAIL"].startswith("@")
        or values["PGADMIN_EMAIL"].endswith("@")
    ):
        raise ExecutableProfileError(
            ".env PGADMIN_EMAIL must be a non-empty email address."
        )


def _validate_web(
    data: Mapping[str, object],
    values: Mapping[str, str],
) -> None:
    """Validate optional WebApp enablement and immutable image identity.

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
    web_image = mapping(mapping(data["web"], "web")["image"], "web.image")
    if values["WEB_IMAGE_NAME"] != str(web_image["name"]):
        raise ExecutableProfileError(
            ".env WEB_IMAGE_NAME must match web.image.name."
        )


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
    _validate_counts_and_resources(values)
    _validate_proxy(values)
    _validate_database(data, values)
    _validate_web(data, values)


__all__ = ["validate_deployment"]
