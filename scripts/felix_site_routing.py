"""
Module: felix_site_routing.py

Description:
    Validates the fixed Felix WebApp/API service inventory and public routing
    declarations kept in the tracked site profile.

Dependencies:
    - scripts/felix_site_contract.py.
"""

from __future__ import annotations

from collections.abc import Mapping

from felix_site_contract import (
    _CANDIDATE_API_ORIGIN,
    _CANDIDATE_WEB_ORIGIN,
    _DIGEST_IMAGE_PATTERN,
    _as_mapping,
    _as_text,
    _require_exact_keys,
    _require_value,
    _validate_public_https,
    FelixSiteProfileError,
)


def validate_services_and_routing(data: Mapping[str, object]) -> None:
    """Validate required services and exact candidate WebApp/API routing.

    Args:
        data: Parsed root site profile.

    Returns:
        None when services, digest, ports, hosts, and network match.

    Raises:
        FelixSiteProfileError: If a required service or route is unsafe or
            drifts from the fixed candidate contract.
    """

    services = _as_mapping(data["services"], "services")
    _require_exact_keys(
        services,
        {"web", "api", "redis", "database", "redisImage"},
        "services",
    )
    for service in ("web", "api", "redis", "database"):
        _require_value(services[service], True, f"services.{service}")
    redis_image = _as_text(services["redisImage"], "services.redisImage")
    if not _DIGEST_IMAGE_PATTERN.fullmatch(redis_image):
        raise FelixSiteProfileError(
            "services.redisImage must be pinned by SHA-256 digest."
        )

    routing = _as_mapping(data["routing"], "routing")
    expected = {
        "containerPort": 8080,
        "apiBaseUrl": _CANDIDATE_API_ORIGIN,
        "domain": "api.felix-app.fe-wi.com",
        "healthPath": "/health",
        "webContainerPort": 80,
        "webBaseUrl": _CANDIDATE_WEB_ORIGIN,
        "webDomain": "felix-app.fe-wi.com",
        "webHealthPath": "/health",
        "traefikNetwork": "traefik-public",
        "sslMode": "proxy",
    }
    _require_exact_keys(routing, set(expected), "routing")
    for key, value in expected.items():
        _require_value(routing[key], value, f"routing.{key}")
    _validate_public_https(str(routing["apiBaseUrl"]), "routing.apiBaseUrl")
    _validate_public_https(str(routing["webBaseUrl"]), "routing.webBaseUrl")
