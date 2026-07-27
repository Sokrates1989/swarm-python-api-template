"""
Module: felix_site_identity.py

Description:
    Validates the exact Felix candidate CORS, Keycloak, callback, API-host, and
    operator public-profile identity shared by the strict Swarm renderer.

Dependencies:
    - scripts/felix_site_contract.py.
    - scripts/release_profile.py.
"""

from __future__ import annotations

from collections.abc import Mapping

from release_profile import SwarmReleaseProfile
from felix_site_contract import (
    _CANDIDATE_API_ORIGIN,
    _CANDIDATE_BACKEND_CLIENT,
    _CANDIDATE_FRONTEND_CLIENT,
    _CANDIDATE_REALM,
    _CANDIDATE_STACK,
    _CANDIDATE_WEB_ORIGIN,
    _as_mapping,
    _require_exact_keys,
    _require_value,
    _validate_public_https,
    FelixSiteProfileError,
)


def _expected_auth_values() -> dict[str, object]:
    """Build the exact public Keycloak and callback contract.

    Returns:
        Expected candidate authentication object.
    """

    return {
        "provider": "keycloak",
        "serverUrl": "https://keycloak.fe-wi.com",
        "issuerUrl": "https://keycloak.fe-wi.com/realms/felix-new",
        "jwksUrl": (
            "https://keycloak.fe-wi.com/realms/felix-new/"
            "protocol/openid-connect/certs"
        ),
        "realm": _CANDIDATE_REALM,
        "frontendClientId": _CANDIDATE_FRONTEND_CLIENT,
        "audience": _CANDIDATE_BACKEND_CLIENT,
        "adminClientId": _CANDIDATE_BACKEND_CLIENT,
        "redirectUris": [
            "https://felix-app.fe-wi.com/auth/callback",
            "felixkc:/callback",
        ],
        "webOrigins": [_CANDIDATE_WEB_ORIGIN],
    }


def _validate_auth_section(data: Mapping[str, object]) -> Mapping[str, object]:
    """Validate the site-owned CORS and Keycloak object.

    Args:
        data: Parsed root site profile.

    Returns:
        Validated authentication mapping.

    Raises:
        FelixSiteProfileError: If origins, clients, callbacks, or URLs drift.
    """

    cors = _as_mapping(data["cors"], "cors")
    _require_exact_keys(cors, {"origins"}, "cors")
    _require_value(cors["origins"], [_CANDIDATE_WEB_ORIGIN], "cors.origins")
    auth = _as_mapping(data["auth"], "auth")
    expected = _expected_auth_values()
    _require_exact_keys(auth, set(expected), "auth")
    _require_value(auth, expected, "auth")
    for field in ("serverUrl", "issuerUrl", "jwksUrl"):
        _validate_public_https(str(auth[field]), f"auth.{field}")
    return auth


def _validate_release_alignment(
    auth: Mapping[str, object],
    release: SwarmReleaseProfile,
) -> None:
    """Require operator public values to match the site contract.

    Args:
        auth: Validated site authentication mapping.
        release: Validated operator-owned public production profile.

    Returns:
        None when both inputs target the same candidate.

    Raises:
        FelixSiteProfileError: If `prod.env` drifts from the site profile.
    """

    expected = {
        "API_BASE_URL": _CANDIDATE_API_ORIGIN,
        "DOMAIN": "api.felix-app.fe-wi.com",
        "CORS_ORIGINS": _CANDIDATE_WEB_ORIGIN,
        "KEYCLOAK_BASE_URL": auth["serverUrl"],
        "KEYCLOAK_ISSUER_URL": auth["issuerUrl"],
        "KEYCLOAK_REALM": auth["realm"],
        "KEYCLOAK_AUDIENCE": auth["audience"],
        "KEYCLOAK_FRONTEND_CLIENT_ID": auth["frontendClientId"],
        "STACK_NAME": _CANDIDATE_STACK,
    }
    for key, expected_value in expected.items():
        if release.values[key] != expected_value:
            raise FelixSiteProfileError(
                f"prod.env {key} must agree with site profile value {expected_value!r}."
            )


def validate_auth_and_cors(
    data: Mapping[str, object],
    release: SwarmReleaseProfile,
) -> None:
    """Validate and align candidate CORS, Keycloak, and callbacks.

    Args:
        data: Parsed root site profile.
        release: Validated operator-owned public production profile.

    Returns:
        None when both inputs agree.

    Raises:
        FelixSiteProfileError: If either source targets legacy/drifting values.
    """

    _validate_release_alignment(_validate_auth_section(data), release)
