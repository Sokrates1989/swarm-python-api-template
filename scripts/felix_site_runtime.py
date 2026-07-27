"""
Module: felix_site_runtime.py

Description:
    Converts the validated wizard-generated Felix deployment profile into the
    non-secret API runtime fields owned by that deployment instance.

Dependencies:
    - scripts/release_profile.py.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from release_profile import SwarmReleaseProfile


def build_release_environment_values(
    release: SwarmReleaseProfile,
) -> dict[str, str]:
    """Build deployment-bound production-safe Felix API runtime values.

    Args:
        release: Validated wizard-generated deployment configuration.

    Returns:
        Runtime values owned by the root `.env`.
    """

    values = release.values
    issuer = values["KEYCLOAK_ISSUER_URL"]
    return {
        "APP_ENVIRONMENT": values["APP_ENVIRONMENT"],
        "BACKEND_APP_ID": values["BACKEND_APP_ID"],
        "APP_PROFILE": values["APP_PROFILE"],
        "PORT": "8080",
        "IMAGE_TAG": values["IMAGE_VERSION"],
        "REDIS_URL": "redis://redis:6379/0",
        "DB_TYPE": values["DB_TYPE"],
        "DB_MODE": values["DB_MODE"],
        "DB_HOST": values["DB_HOST"],
        "DB_PORT": values["DB_PORT"],
        "DB_NAME": values["DB_NAME"],
        "DB_USER": values["DB_USER"],
        "CORS_ORIGINS": values["CORS_ORIGINS"],
        "AUTH_PROVIDER": values["AUTH_PROVIDER"],
        "KEYCLOAK_SERVER_URL": values["KEYCLOAK_BASE_URL"],
        "KEYCLOAK_REALM": values["KEYCLOAK_REALM"],
        "KEYCLOAK_CLIENT_ID": values["KEYCLOAK_FRONTEND_CLIENT_ID"],
        "KEYCLOAK_ISSUER_URL": issuer,
        "KEYCLOAK_JWKS_URL": issuer + "/protocol/openid-connect/certs",
        "KEYCLOAK_ENFORCE_AUDIENCE": "true",
        "KEYCLOAK_AUDIENCE": values["KEYCLOAK_AUDIENCE"],
        "KEYCLOAK_ADMIN_CLIENT_ID": values["KEYCLOAK_AUDIENCE"],
    }


def build_profile_fingerprint(
    data: Mapping[str, object],
    release: SwarmReleaseProfile,
) -> str:
    """Compute a deterministic site plus deployment fingerprint.

    Args:
        data: Validated parsed JSON site profile.
        release: Validated wizard-generated deployment configuration.

    Returns:
        Lowercase SHA-256 of canonical compact public inputs.
    """

    canonical = json.dumps(
        {"site": data, "deploymentFingerprint": release.fingerprint},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
