"""
Module: release_profile_urls.py

Description:
    Validates public Felix API, WebApp, Keycloak, CORS, and optional pgAdmin
    endpoint relationships without permitting local, placeholder, wildcard,
    credential-bearing, or legacy URLs.

Dependencies:
    - scripts/release_profile_errors.py.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from urllib.parse import SplitResult, urlsplit

from release_profile_errors import SwarmReleaseProfileError


_PLACEHOLDER_MARKERS = ("change_me", "changeme", "placeholder", "todo", "xxx")
_PLACEHOLDER_HOSTS = frozenset(("example.com", "example.net", "example.org"))
_LOCAL_HOSTS = frozenset(
    ("0.0.0.0", "10.0.2.2", "host.docker.internal", "localhost")
)
_CANDIDATE_WEB_ORIGIN = "https://felix-app.fe-wi.com"
_CANDIDATE_API_ORIGIN = "https://api.felix-app.fe-wi.com"
_PROTECTED_WEB_ORIGIN = "https://felix.app.fe-wi.com"


def _is_placeholder(value: str) -> bool:
    """Report whether text contains an obvious placeholder.

    Args:
        value: Public profile text.

    Returns:
        True for a common placeholder marker; otherwise False.
    """

    lowered = value.casefold()
    return any(marker in lowered for marker in _PLACEHOLDER_MARKERS)


def _is_non_public_host(hostname: str) -> bool:
    """Report whether a host is local, emulator-only, private, or link-local.

    Args:
        hostname: Lowercase parsed URL hostname.

    Returns:
        True when the host is unsuitable for production.
    """

    if (
        hostname in _LOCAL_HOSTS
        or hostname.endswith(".localhost")
        or hostname.endswith(".local")
        or hostname.endswith(".internal")
    ):
        return True
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return not address.is_global


def _is_placeholder_host(hostname: str) -> bool:
    """Report whether a host belongs to reserved example space.

    Args:
        hostname: Lowercase parsed URL hostname.

    Returns:
        True for `.invalid` and conventional example domains.
    """

    return (
        hostname.endswith(".invalid")
        or hostname in _PLACEHOLDER_HOSTS
        or any(hostname.endswith(f".{item}") for item in _PLACEHOLDER_HOSTS)
    )


def _parse_public_url(
    key: str,
    value: str,
    *,
    origin_only: bool,
) -> SplitResult:
    """Validate one HTTPS production URL.

    Args:
        key: Profile field used in diagnostics.
        value: Candidate absolute public URL.
        origin_only: Whether paths other than `/` are forbidden.

    Returns:
        Parsed URL after production plausibility checks.

    Raises:
        SwarmReleaseProfileError: If the URL is unsafe, local, placeholder, or
            not an origin where an origin is required.
    """

    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise SwarmReleaseProfileError(f"{key} must be an absolute HTTPS URL.")
    if parsed.username is not None or parsed.password is not None:
        raise SwarmReleaseProfileError(f"{key} must not contain URL credentials.")
    if parsed.query or parsed.fragment:
        raise SwarmReleaseProfileError(
            f"{key} must not contain a query or fragment."
        )
    if "*" in parsed.netloc:
        raise SwarmReleaseProfileError(f"{key} must not contain a wildcard host.")
    try:
        parsed.port
    except ValueError as error:
        raise SwarmReleaseProfileError(f"{key} contains an invalid port.") from error
    if origin_only and parsed.path not in ("", "/"):
        raise SwarmReleaseProfileError(f"{key} must be an origin without a path.")
    hostname = parsed.hostname.casefold()
    if _is_non_public_host(hostname):
        raise SwarmReleaseProfileError(f"{key} must not use a local or private host.")
    if _is_placeholder_host(hostname) or _is_placeholder(value):
        raise SwarmReleaseProfileError(f"{key} must not use a placeholder host.")
    return parsed


def _validate_api(values: Mapping[str, str]) -> SplitResult:
    """Validate the exact candidate API origin and host relationship.

    Args:
        values: Complete allowlisted profile mapping.

    Returns:
        Parsed candidate API URL.

    Raises:
        SwarmReleaseProfileError: If API URL or domain values drift.
    """

    api = _parse_public_url("API_BASE_URL", values["API_BASE_URL"], origin_only=False)
    if api.path.rstrip("/") == "/api" or api.path.startswith("/api/"):
        raise SwarmReleaseProfileError(
            "API_BASE_URL must not contain a redundant /api service prefix."
        )
    if api.path not in ("", "/"):
        raise SwarmReleaseProfileError("API_BASE_URL must not contain a path.")
    if api.hostname != values["DOMAIN"].casefold():
        raise SwarmReleaseProfileError("DOMAIN must match the API_BASE_URL hostname.")
    if values["API_BASE_URL"].rstrip("/") != _CANDIDATE_API_ORIGIN:
        raise SwarmReleaseProfileError(
            f"API_BASE_URL must equal {_CANDIDATE_API_ORIGIN!r}."
        )
    return api


def _validate_web(values: Mapping[str, str]) -> SplitResult:
    """Validate the exact candidate WebApp origin and host relationship.

    Args:
        values: Complete allowlisted profile mapping.

    Returns:
        Parsed candidate WebApp URL.

    Raises:
        SwarmReleaseProfileError: If WebApp URL or domain values drift.
    """

    web = _parse_public_url(
        "WEB_BASE_URL",
        values["WEB_BASE_URL"],
        origin_only=True,
    )
    if web.hostname != values["WEB_DOMAIN"].casefold():
        raise SwarmReleaseProfileError(
            "WEB_DOMAIN must match the WEB_BASE_URL hostname."
        )
    if values["WEB_BASE_URL"].rstrip("/") != _CANDIDATE_WEB_ORIGIN:
        raise SwarmReleaseProfileError(
            f"WEB_BASE_URL must equal {_CANDIDATE_WEB_ORIGIN!r}."
        )
    return web


def _validate_keycloak(values: Mapping[str, str]) -> None:
    """Validate exact candidate Keycloak base and realm issuer URLs.

    Args:
        values: Complete allowlisted profile mapping.

    Returns:
        None when issuer and base URL agree.

    Raises:
        SwarmReleaseProfileError: If Keycloak endpoints are malformed or drift.
    """

    _parse_public_url(
        "KEYCLOAK_BASE_URL",
        values["KEYCLOAK_BASE_URL"],
        origin_only=True,
    )
    _parse_public_url(
        "KEYCLOAK_ISSUER_URL",
        values["KEYCLOAK_ISSUER_URL"],
        origin_only=False,
    )
    base = values["KEYCLOAK_BASE_URL"].rstrip("/")
    expected_issuer = f"{base}/realms/{values['KEYCLOAK_REALM']}"
    if values["KEYCLOAK_ISSUER_URL"] != expected_issuer:
        raise SwarmReleaseProfileError(
            "KEYCLOAK_ISSUER_URL must be the declared realm below the base URL."
        )


def _validate_cors(values: Mapping[str, str]) -> None:
    """Validate exact candidate CORS ownership without legacy overlap.

    Args:
        values: Complete allowlisted profile mapping.

    Returns:
        None when only the candidate WebApp origin is declared.

    Raises:
        SwarmReleaseProfileError: If origins duplicate, drift, or claim legacy.
    """

    origins = values["CORS_ORIGINS"].split(",")
    if len(origins) != len(set(origins)):
        raise SwarmReleaseProfileError("CORS_ORIGINS must not contain duplicates.")
    for origin in origins:
        _parse_public_url("CORS_ORIGINS", origin, origin_only=True)
    if _PROTECTED_WEB_ORIGIN in origins:
        raise SwarmReleaseProfileError(
            "Candidate CORS_ORIGINS must not claim the protected legacy origin."
        )
    if origins != [values["WEB_BASE_URL"].rstrip("/")]:
        raise SwarmReleaseProfileError("CORS_ORIGINS must equal WEB_BASE_URL.")


def _validate_pgadmin_hosts(
    values: Mapping[str, str],
    api: SplitResult,
    web: SplitResult,
) -> None:
    """Keep enabled pgAdmin on a distinct public management hostname.

    Args:
        values: Complete allowlisted profile mapping.
        api: Parsed candidate API URL.
        web: Parsed candidate WebApp URL.

    Returns:
        None when disabled or routed on a distinct public host.

    Raises:
        SwarmReleaseProfileError: If management routing overlaps app hosts.
    """

    if values["PGADMIN_ENABLED"] != "true":
        return
    pgadmin = _parse_public_url(
        "PGADMIN_DOMAIN",
        f"https://{values['PGADMIN_DOMAIN']}",
        origin_only=True,
    )
    if pgadmin.hostname in {api.hostname, web.hostname}:
        raise SwarmReleaseProfileError(
            "PGADMIN_DOMAIN must use a distinct management hostname."
        )


def validate_urls(values: Mapping[str, str]) -> None:
    """Validate all public URL relationships and legacy isolation.

    Args:
        values: Complete allowlisted profile mapping.

    Returns:
        None when every public URL is plausible and mutually consistent.

    Raises:
        SwarmReleaseProfileError: If any endpoint is unsafe or drifting.
    """

    api = _validate_api(values)
    web = _validate_web(values)
    _validate_keycloak(values)
    _validate_cors(values)
    _validate_pgadmin_hosts(values, api, web)
