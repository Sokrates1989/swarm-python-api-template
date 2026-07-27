"""
Module: release_profile_deployment.py

Description:
    Validates the guided Felix deployment-instance fields that may vary by
    Swarm host: database placement, proxy/TLS mode, resource limits, images,
    storage, WebApp enablement, and optional pgAdmin metadata.

Dependencies:
    - scripts/release_profile_errors.py.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import PurePosixPath

from release_profile_errors import SwarmReleaseProfileError


_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{1,127}")
_IMAGE_NAME_PATTERN = re.compile(
    r"[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)+"
)
_SEMANTIC_VERSION_PATTERN = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z.-]+)?"
)
_MEMORY_LIMIT_PATTERN = re.compile(r"[1-9][0-9]*(?:M|G)")
_HOST_PATTERN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?")
_EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_API_IMAGE = "sokrates1989/python-api-felix"


def _parse_bounded_integer(
    key: str,
    value: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    """Parse one canonical decimal value inside an inclusive range.

    Args:
        key: Public field name used in diagnostics.
        value: Decimal text to parse.
        minimum: Smallest accepted value.
        maximum: Largest accepted value.

    Returns:
        Parsed integer.

    Raises:
        SwarmReleaseProfileError: If the value is not canonical decimal data
            or falls outside the requested range.
    """

    if not value.isdecimal() or (len(value) > 1 and value.startswith("0")):
        raise SwarmReleaseProfileError(f"{key} must be a canonical integer.")
    parsed = int(value)
    if not minimum <= parsed <= maximum:
        raise SwarmReleaseProfileError(
            f"{key} must be between {minimum} and {maximum}."
        )
    return parsed


def _validate_database(values: Mapping[str, str]) -> None:
    """Validate local or secret-file-safe external PostgreSQL metadata.

    Args:
        values: Complete public deployment mapping.

    Returns:
        None when database mode and connection fields are safe.

    Raises:
        SwarmReleaseProfileError: If mode or connection metadata is invalid.
    """

    mode = values["DB_MODE"]
    if mode not in {"local", "external"}:
        raise SwarmReleaseProfileError("DB_MODE must equal 'local' or 'external'.")
    host = values["DB_HOST"]
    if not _HOST_PATTERN.fullmatch(host) or "@" in host or "/" in host:
        raise SwarmReleaseProfileError(
            "DB_HOST must be a hostname or IP without credentials."
        )
    _parse_bounded_integer("DB_PORT", values["DB_PORT"], minimum=1, maximum=65535)
    for key in ("DB_NAME", "DB_USER"):
        if not _IDENTIFIER_PATTERN.fullmatch(values[key]):
            raise SwarmReleaseProfileError(f"{key} contains an invalid identifier.")
    if mode == "local" and (host != "postgres" or values["DB_PORT"] != "5432"):
        raise SwarmReleaseProfileError(
            "Local PostgreSQL requires DB_HOST=postgres and DB_PORT=5432."
        )
    if mode == "external" and host == "postgres":
        raise SwarmReleaseProfileError(
            "External PostgreSQL must not target the local service hostname."
        )


def _validate_proxy(values: Mapping[str, str]) -> None:
    """Validate Traefik/TLS or externally managed published-port routing.

    Args:
        values: Complete public deployment mapping.

    Returns:
        None when proxy, SSL, network, and port fields agree.

    Raises:
        SwarmReleaseProfileError: If the routing combination is unsupported.
    """

    proxy_type = values["PROXY_TYPE"]
    ssl_mode = values["SSL_MODE"]
    if proxy_type not in {"traefik", "none"}:
        raise SwarmReleaseProfileError("PROXY_TYPE must equal 'traefik' or 'none'.")
    if proxy_type == "traefik":
        if ssl_mode not in {"letsencrypt", "proxy"}:
            raise SwarmReleaseProfileError(
                "Traefik SSL_MODE must equal 'letsencrypt' or 'proxy'."
            )
        if not _IDENTIFIER_PATTERN.fullmatch(values["TRAEFIK_NETWORK"]):
            raise SwarmReleaseProfileError(
                "TRAEFIK_NETWORK contains an invalid identifier."
            )
    elif ssl_mode != "proxy" or values["TRAEFIK_NETWORK"] != "none":
        raise SwarmReleaseProfileError(
            "No-proxy mode requires SSL_MODE=proxy and TRAEFIK_NETWORK=none."
        )
    _parse_bounded_integer(
        "API_PUBLISHED_PORT",
        values["API_PUBLISHED_PORT"],
        minimum=1,
        maximum=65535,
    )
    _parse_bounded_integer(
        "WEB_PUBLISHED_PORT",
        values["WEB_PUBLISHED_PORT"],
        minimum=1,
        maximum=65535,
    )
    if values["API_PUBLISHED_PORT"] == values["WEB_PUBLISHED_PORT"]:
        raise SwarmReleaseProfileError(
            "API_PUBLISHED_PORT and WEB_PUBLISHED_PORT must be distinct."
        )


def _validate_api_resources(values: Mapping[str, str]) -> None:
    """Validate API image, replicas, memory, and host storage ownership.

    Args:
        values: Complete public deployment mapping.

    Returns:
        None when API resource fields are production-safe.

    Raises:
        SwarmReleaseProfileError: If an image, resource, or path is invalid.
    """

    if values["IMAGE_NAME"] != _API_IMAGE:
        raise SwarmReleaseProfileError(f"IMAGE_NAME must equal {_API_IMAGE!r}.")
    if not _SEMANTIC_VERSION_PATTERN.fullmatch(values["IMAGE_VERSION"]):
        raise SwarmReleaseProfileError(
            "IMAGE_VERSION must be an immutable semantic version."
        )
    _parse_bounded_integer(
        "API_REPLICAS", values["API_REPLICAS"], minimum=1, maximum=20
    )
    if not _MEMORY_LIMIT_PATTERN.fullmatch(values["MEMORY_LIMIT"]):
        raise SwarmReleaseProfileError(
            "MEMORY_LIMIT must be a positive M or G value."
        )
    data_root = PurePosixPath(values["DATA_ROOT"])
    if not data_root.is_absolute() or data_root in {
        PurePosixPath("/"),
        PurePosixPath("/swarm"),
    }:
        raise SwarmReleaseProfileError(
            "DATA_ROOT must be a dedicated absolute deployment directory."
        )
    if ".." in data_root.parts:
        raise SwarmReleaseProfileError("DATA_ROOT must not contain '..'.")


def _validate_web(values: Mapping[str, str]) -> None:
    """Validate the required WebApp image and bounded resource fields.

    Args:
        values: Complete public deployment mapping.

    Returns:
        None when WebApp enablement, image, version, and replicas agree.

    Raises:
        SwarmReleaseProfileError: If WebApp fields are incomplete or unsafe.
    """

    if values["WEB_ENABLED"] != "true":
        raise SwarmReleaseProfileError(
            "WEB_ENABLED must be 'true' for the Felix full stack."
        )
    if not _IMAGE_NAME_PATTERN.fullmatch(values["WEB_IMAGE_NAME"]):
        raise SwarmReleaseProfileError("WEB_IMAGE_NAME is invalid.")
    if not _SEMANTIC_VERSION_PATTERN.fullmatch(values["WEB_IMAGE_VERSION"]):
        raise SwarmReleaseProfileError(
            "WEB_IMAGE_VERSION must be an immutable semantic version."
        )
    _parse_bounded_integer(
        "WEB_REPLICAS", values["WEB_REPLICAS"], minimum=1, maximum=20
    )
    if not _MEMORY_LIMIT_PATTERN.fullmatch(values["WEB_MEMORY_LIMIT"]):
        raise SwarmReleaseProfileError(
            "WEB_MEMORY_LIMIT must be a positive M or G value."
        )


def _validate_pgadmin(values: Mapping[str, str]) -> None:
    """Validate optional pgAdmin public metadata without accepting secrets.

    Args:
        values: Complete public deployment mapping.

    Returns:
        None when pgAdmin enablement, hostname, email, and replicas agree.

    Raises:
        SwarmReleaseProfileError: If optional management metadata is unsafe.
    """

    enabled = values["PGADMIN_ENABLED"]
    if enabled not in {"true", "false"}:
        raise SwarmReleaseProfileError("PGADMIN_ENABLED must be 'true' or 'false'.")
    if enabled == "false":
        disabled = (
            values["PGADMIN_DOMAIN"] == "disabled"
            and values["PGADMIN_EMAIL"] == "disabled"
            and values["PGADMIN_REPLICAS"] == "0"
        )
        if not disabled:
            raise SwarmReleaseProfileError(
                "Disabled pgAdmin requires disabled public fields and zero replicas."
            )
        return
    if values["DB_MODE"] != "local":
        raise SwarmReleaseProfileError(
            "pgAdmin can be enabled only with local PostgreSQL."
        )
    if values["PROXY_TYPE"] != "traefik":
        raise SwarmReleaseProfileError(
            "pgAdmin requires Traefik routing in this deployment profile."
        )
    if not _EMAIL_PATTERN.fullmatch(values["PGADMIN_EMAIL"]):
        raise SwarmReleaseProfileError("PGADMIN_EMAIL must be a valid email.")
    _parse_bounded_integer(
        "PGADMIN_REPLICAS",
        values["PGADMIN_REPLICAS"],
        minimum=1,
        maximum=1,
    )


def validate_deployment(values: Mapping[str, str]) -> None:
    """Validate all guided non-secret deployment-instance settings.

    Args:
        values: Complete public deployment mapping.

    Returns:
        None when all variable deployment fields are mutually consistent.

    Raises:
        SwarmReleaseProfileError: If any guided deployment field is unsafe.
    """

    _validate_database(values)
    _validate_proxy(values)
    _validate_api_resources(values)
    _validate_web(values)
    _validate_pgadmin(values)
