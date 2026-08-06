"""
Module: executable_profile_runtime.py

Description:
    Resolves active file-backed secret mounts, capability environment, exact
    runtime allowlists, and public fingerprints for validated executable site
    profiles.

Dependencies:
    - Python standard library.
    - scripts/executable_profile_support.py.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from executable_profile_support import (
    DIRECT_SECRET_KEYS,
    FALSE_DEBUG_KEYS,
    OPERATIONAL_DEPLOYMENT_KEYS,
    SECRET_PATTERN,
    ExecutableProfileError,
    mapping,
    require_keys,
    sequence,
    text,
)


@dataclass(frozen=True)
class SecretMount:
    """Describes one file-backed Docker secret consumed by the API.

    Attributes:
        name: External Docker secret identifier.
        env_key: API environment field containing the mounted file path.
        target: Absolute in-container secret file path.
    """

    name: str
    env_key: str
    target: str


def _validated_mount(
    raw_mount: object,
    field: str,
) -> SecretMount:
    """Validate and normalize one Docker secret mount.

    Args:
        raw_mount: Parsed mount object.
        field: Diagnostic field path.

    Returns:
        Validated immutable mount.

    Raises:
        ExecutableProfileError: If name, file field, or target is unsafe.
    """

    mount = mapping(raw_mount, field)
    require_keys(mount, {"name", "envKey", "target"}, field)
    name = text(mount["name"], f"{field}.name")
    env_key = text(mount["envKey"], f"{field}.envKey")
    target = text(mount["target"], f"{field}.target")
    if not SECRET_PATTERN.fullmatch(name):
        raise ExecutableProfileError(f"{field}.name is unsafe.")
    if not env_key.endswith("_FILE"):
        raise ExecutableProfileError(f"{field}.envKey must end in _FILE.")
    if target != f"/run/secrets/{name}":
        raise ExecutableProfileError(
            f"{field}.target must match its secret name."
        )
    return SecretMount(name, env_key, target)


def parse_mounts(
    data: Mapping[str, object],
) -> tuple[tuple[SecretMount, ...], dict[str, str]]:
    """Resolve base plus enabled-capability secret mounts and environment.

    Args:
        data: Validated profile data.

    Returns:
        Active mounts and capability environment values.

    Raises:
        ExecutableProfileError: If mounts collide or expose direct secrets.
    """

    mounts = tuple(
        _validated_mount(raw_mount, f"secretMounts[{index}]")
        for index, raw_mount in enumerate(
            sequence(data["secretMounts"], "secretMounts")
        )
    )
    active_mounts = list(mounts)
    capability_environment: dict[str, str] = {}
    capabilities = mapping(data.get("capabilities", {}), "capabilities")
    for name, raw_capability in capabilities.items():
        capability = mapping(raw_capability, f"capabilities.{name}")
        if capability.get("enabled") is not True:
            continue
        environment = mapping(
            capability.get("environment", {}),
            f"capabilities.{name}.environment",
        )
        for key, value in environment.items():
            if key in DIRECT_SECRET_KEYS or key.endswith(
                ("PASSWORD", "SECRET", "TOKEN")
            ):
                raise ExecutableProfileError(
                    f"capabilities.{name}.environment contains direct "
                    f"secret field {key}."
                )
            capability_environment[key] = text(
                value,
                f"capabilities.{name}.environment.{key}",
            )
        active_mounts.extend(
            _validated_mount(
                raw_mount,
                f"capabilities.{name}.secretMounts[{index}]",
            )
            for index, raw_mount in enumerate(
                sequence(
                    capability.get("secretMounts", []),
                    f"capabilities.{name}.secretMounts",
                )
            )
        )
    names = [mount.name for mount in active_mounts]
    env_keys = [mount.env_key for mount in active_mounts]
    if len(names) != len(set(names)) or len(env_keys) != len(set(env_keys)):
        raise ExecutableProfileError("Active Docker secret mounts collide.")
    return tuple(active_mounts), capability_environment


def runtime_environment(
    data: Mapping[str, object],
    deployment: Mapping[str, str],
    mounts: Sequence[SecretMount],
    capability_environment: Mapping[str, str],
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Build and validate the exact API runtime environment.

    Args:
        data: Validated site profile.
        deployment: Validated root environment.
        mounts: Active API secret mounts.
        capability_environment: Enabled capability public fields.

    Returns:
        Runtime value mapping and ordered allowlist.

    Raises:
        ExecutableProfileError: If allowlists drift or debug/secrets are unsafe.
    """

    raw_environment = mapping(data["environment"], "environment")
    environment = {
        key: text(value, f"environment.{key}")
        for key, value in raw_environment.items()
    }
    environment.update(capability_environment)
    environment.update(
        {
            "APP_ENVIRONMENT": deployment["APP_ENVIRONMENT"],
            "BACKEND_APP_ID": deployment["BACKEND_APP_ID"],
            "APP_PROFILE": deployment["APP_PROFILE"],
            "IMAGE_TAG": deployment["IMAGE_VERSION"],
            "DB_TYPE": deployment["DB_TYPE"],
            "DB_MODE": deployment["DB_MODE"],
            "DB_HOST": deployment["DB_HOST"],
            "DB_PORT": deployment["DB_PORT"],
            "DB_NAME": deployment["DB_NAME"],
            "DB_USER": deployment["DB_USER"],
            "CORS_ORIGINS": deployment["CORS_ORIGINS"],
        }
    )
    auth = mapping(data.get("auth", {"provider": "none"}), "auth")
    if auth.get("provider") == "keycloak":
        issuer_url = deployment["KEYCLOAK_ISSUER_URL"].rstrip("/")
        environment.update(
            {
                "AUTH_PROVIDER": "keycloak",
                "KEYCLOAK_SERVER_URL": deployment["KEYCLOAK_BASE_URL"],
                "KEYCLOAK_REALM": deployment["KEYCLOAK_REALM"],
                "KEYCLOAK_CLIENT_ID": deployment[
                    "KEYCLOAK_FRONTEND_CLIENT_ID"
                ],
                "KEYCLOAK_ISSUER_URL": issuer_url,
                "KEYCLOAK_JWKS_URL": (
                    f"{issuer_url}/protocol/openid-connect/certs"
                ),
                "KEYCLOAK_ENFORCE_AUDIENCE": "true",
                "KEYCLOAK_AUDIENCE": deployment["KEYCLOAK_AUDIENCE"],
                "KEYCLOAK_ADMIN_CLIENT_ID": deployment[
                    "KEYCLOAK_BACKEND_CLIENT_ID"
                ],
            }
        )
    if deployment["ADVANCED_LOGGING_ENABLED"] != "true":
        environment["LOG_LEVEL"] = "WARNING"
    for key in FALSE_DEBUG_KEYS:
        if key in environment and environment[key].lower() != "false":
            raise ExecutableProfileError(
                f"environment.{key} must remain false."
            )
    if environment.get("LOG_LEVEL", "").upper() == "DEBUG":
        raise ExecutableProfileError(
            "environment.LOG_LEVEL must not enable DEBUG."
        )
    if DIRECT_SECRET_KEYS & set(environment):
        raise ExecutableProfileError(
            "Direct secret environment fields are forbidden."
        )
    env_keys = tuple(
        text(value, f"envKeys[{index}]")
        for index, value in enumerate(sequence(data["envKeys"], "envKeys"))
    )
    expected_keys = set(environment) | {mount.env_key for mount in mounts}
    if set(env_keys) != expected_keys or len(env_keys) != len(set(env_keys)):
        raise ExecutableProfileError(
            "envKeys must exactly match public environment and active "
            "secret file fields."
        )
    return environment, env_keys


def public_fingerprint(
    data: Mapping[str, object],
    deployment: Mapping[str, str],
) -> str:
    """Compute deterministic SHA-256 evidence for public inputs.

    Args:
        data: Validated site profile.
        deployment: Validated root environment.

    Returns:
        Lowercase SHA-256 digest excluding operator-only reminder metadata
        that cannot affect rendered or runtime behavior.
    """

    evidence_deployment = {
        key: value
        for key, value in deployment.items()
        if key not in OPERATIONAL_DEPLOYMENT_KEYS
    }
    canonical = json.dumps(
        {"site": data, "deployment": evidence_deployment},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "SecretMount",
    "parse_mounts",
    "public_fingerprint",
    "runtime_environment",
]
