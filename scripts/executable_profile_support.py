"""
Module: executable_profile_support.py

Description:
    Defines shared constants, errors, strict JSON/dotenv parsing, and fixed
    identity derivation for schema-5 executable deployment profiles. These
    helpers contain no application identity and perform no runtime mutation.

Dependencies:
    - Python standard library only.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path


PROFILE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
SEMVER_PATTERN = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
)
IMAGE_PATTERN = re.compile(r"[a-z0-9][a-z0-9._/-]*")
DIGEST_IMAGE_PATTERN = re.compile(
    r"[a-z0-9][a-z0-9._/-]*@sha256:[a-f0-9]{64}"
)
SECRET_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{2,127}")
MEMORY_PATTERN = re.compile(
    r"[1-9][0-9]*(?:[KMGTP]i?B?|B)",
    re.IGNORECASE,
)
DIRECT_SECRET_KEYS = frozenset(
    {
        "DB_PASSWORD",
        "KEYCLOAK_ADMIN_CLIENT_SECRET",
        "KEYCLOAK_CLIENT_SECRET",
        "PGADMIN_PASSWORD",
        "WEB_PUSH_VAPID_PRIVATE_KEY",
    }
)
FALSE_DEBUG_KEYS = frozenset(
    {
        "DEBUG",
        "DEBUG_ENABLED",
        "SQL_ECHO_ENABLED",
        "ENABLE_HTTP_DEBUG_LOGGING",
        "LOG_REQUEST_HEADERS",
        "LOG_REQUEST_BODY",
        "LOG_RESPONSE_HEADERS",
        "LOG_RESPONSE_BODY",
        "AI_CHAT_DEBUG_ENABLED",
        "AI_CHAT_DEBUG_INCLUDE_PROMPTS",
    }
)
DEPLOYMENT_KEYS = (
    "PROFILE_SCHEMA_VERSION",
    "DEPLOYMENT_PROFILE_ID",
    "APP_ID",
    "APP_ENVIRONMENT",
    "APP_PROFILE",
    "BACKEND_APP_ID",
    "BACKEND_DATA_PROFILE",
    "AUTH_PROVIDER",
    "API_BASE_URL",
    "DOMAIN",
    "WEB_BASE_URL",
    "WEB_DOMAIN",
    "CORS_ORIGINS",
    "KEYCLOAK_BASE_URL",
    "KEYCLOAK_ISSUER_URL",
    "KEYCLOAK_REALM",
    "KEYCLOAK_AUDIENCE",
    "KEYCLOAK_FRONTEND_CLIENT_ID",
    "KEYCLOAK_BACKEND_CLIENT_ID",
    "STACK_NAME",
    "STACK_FAMILY",
    "STACK_ROLE",
    "PRIMARY_SERVICE",
    "DB_TYPE",
    "DB_MODE",
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "DB_USER",
    "PROXY_TYPE",
    "SSL_MODE",
    "TRAEFIK_NETWORK",
    "TRAEFIK_CERT_RESOLVER",
    "API_PUBLISHED_PORT",
    "WEB_PUBLISHED_PORT",
    "PGADMIN_PUBLISHED_PORT",
    "IMAGE_NAME",
    "IMAGE_VERSION",
    "API_REPLICAS",
    "MEMORY_LIMIT",
    "DATA_ROOT",
    "PGADMIN_ENABLED",
    "PGADMIN_DOMAIN",
    "PGADMIN_EMAIL",
    "PGADMIN_REPLICAS",
    "WEB_ENABLED",
    "WEB_IMAGE_NAME",
    "WEB_IMAGE_VERSION",
    "WEB_REPLICAS",
    "WEB_MEMORY_LIMIT",
)
DEPLOYMENT_KEY_SET = frozenset(DEPLOYMENT_KEYS)


class ExecutableProfileError(ValueError):
    """Reports malformed, unsafe, incomplete, or drifting profile input."""


def mapping(value: object, field: str) -> Mapping[str, object]:
    """Return a JSON object or raise a profile error.

    Args:
        value: Parsed JSON value.
        field: Diagnostic field name.

    Returns:
        Validated mapping.

    Raises:
        ExecutableProfileError: If ``value`` is not an object.
    """

    if not isinstance(value, Mapping):
        raise ExecutableProfileError(f"{field} must be a JSON object.")
    return value


def sequence(value: object, field: str) -> Sequence[object]:
    """Return a non-string JSON array or raise a profile error.

    Args:
        value: Parsed JSON value.
        field: Diagnostic field name.

    Returns:
        Validated sequence.

    Raises:
        ExecutableProfileError: If ``value`` is not an array.
    """

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ExecutableProfileError(f"{field} must be a JSON array.")
    return value


def text(value: object, field: str) -> str:
    """Return non-empty trimmed text.

    Args:
        value: Parsed JSON value.
        field: Diagnostic field name.

    Returns:
        Validated string.

    Raises:
        ExecutableProfileError: If the value is empty, non-text, or untrimmed.
    """

    if not isinstance(value, str) or not value or value != value.strip():
        raise ExecutableProfileError(f"{field} must be non-empty trimmed text.")
    return value


def require_keys(
    value: Mapping[str, object],
    required: set[str],
    field: str,
) -> None:
    """Require a mapping to contain a minimum key set.

    Args:
        value: Mapping under validation.
        required: Required keys.
        field: Diagnostic field name.

    Raises:
        ExecutableProfileError: If any required key is missing.
    """

    missing = sorted(required - set(value))
    if missing:
        raise ExecutableProfileError(
            f"{field} is missing required keys: {', '.join(missing)}"
        )


def load_json(path: Path) -> Mapping[str, object]:
    """Load strict UTF-8 JSON while rejecting duplicate keys.

    Args:
        path: JSON file to load.

    Returns:
        Parsed root mapping.

    Raises:
        ExecutableProfileError: If the file is missing or invalid.
    """

    def unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        """Build one object while rejecting duplicate keys.

        Args:
            pairs: Ordered JSON object pairs.

        Returns:
            Unique-key dictionary.

        Raises:
            ExecutableProfileError: If one key occurs more than once.
        """

        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ExecutableProfileError(
                    f"Duplicate JSON key is forbidden: {key}"
                )
            result[key] = value
        return result

    if not path.is_file():
        raise ExecutableProfileError(f"Site profile is missing: {path}")
    try:
        parsed = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=unique_pairs,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ExecutableProfileError(
            f"Invalid site profile {path}: {error}"
        ) from error
    return mapping(parsed, str(path))


def read_env(path: Path) -> dict[str, str]:
    """Parse an exact generated dotenv file without evaluating shell syntax.

    Args:
        path: Root environment path.

    Returns:
        Ordered deployment values.

    Raises:
        ExecutableProfileError: If syntax, keys, or duplicates are invalid.
    """

    if not path.is_file():
        raise ExecutableProfileError(
            f"Root deployment environment is missing: {path}"
        )
    values: dict[str, str] = {}
    for number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        1,
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export ") or "=" not in line:
            raise ExecutableProfileError(
                f"Invalid .env syntax on line {number}."
            )
        key, value = line.split("=", 1)
        if key not in DEPLOYMENT_KEY_SET:
            raise ExecutableProfileError(f"Unknown generated .env key: {key}")
        if key in values:
            raise ExecutableProfileError(
                f"Duplicate generated .env key: {key}"
            )
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    missing = [key for key in DEPLOYMENT_KEYS if key not in values]
    if missing:
        raise ExecutableProfileError(
            f"Root .env is missing generated keys: {', '.join(missing)}"
        )
    return values


def config_path(root: Path, config_id: str) -> Path:
    """Resolve a selected profile without allowing path traversal.

    Args:
        root: Repository root.
        config_id: Site-config filename stem.

    Returns:
        Canonical profile path.

    Raises:
        ExecutableProfileError: If the ID is unsafe.
    """

    if not PROFILE_ID_PATTERN.fullmatch(config_id):
        raise ExecutableProfileError("Deployment profile ID is unsafe.")
    return (root / "site-configs" / f"{config_id}.json").resolve()


def fixed_deployment_values(
    data: Mapping[str, object],
    config_id: str,
) -> dict[str, str]:
    """Derive non-editable deployment identity from a site config.

    Args:
        data: Parsed site profile.
        config_id: Selected site-config ID.

    Returns:
        Fixed public root environment fields.
    """

    stack = mapping(data["stack"], "stack")
    routing = mapping(data["routing"], "routing")
    database = mapping(data["database"], "database")
    image = mapping(data["image"], "image")
    environment = mapping(data["environment"], "environment")
    cors = mapping(data["cors"], "cors")
    auth = mapping(data.get("auth", {"provider": "none"}), "auth")
    web_enabled = bool(mapping(data["services"], "services").get("web", False))
    provider = str(auth.get("provider", "none"))
    return {
        "PROFILE_SCHEMA_VERSION": str(data["version"]),
        "DEPLOYMENT_PROFILE_ID": config_id,
        "APP_ID": text(data["appId"], "appId"),
        "APP_ENVIRONMENT": str(
            environment.get("APP_ENVIRONMENT", "production")
        ),
        "APP_PROFILE": str(environment.get("APP_PROFILE", data["appId"])),
        "BACKEND_APP_ID": str(
            environment.get("BACKEND_APP_ID", data["appId"])
        ),
        "BACKEND_DATA_PROFILE": str(database["type"]),
        "AUTH_PROVIDER": provider,
        "API_BASE_URL": str(routing["apiBaseUrl"]),
        "DOMAIN": str(routing["domain"]),
        "WEB_BASE_URL": (
            str(routing.get("webBaseUrl", "")) if web_enabled else ""
        ),
        "WEB_DOMAIN": (
            str(routing.get("webDomain", "")) if web_enabled else ""
        ),
        "CORS_ORIGINS": ",".join(
            str(item) for item in sequence(cors["origins"], "cors.origins")
        ),
        "KEYCLOAK_BASE_URL": str(auth.get("serverUrl", "")),
        "KEYCLOAK_ISSUER_URL": str(auth.get("issuerUrl", "")),
        "KEYCLOAK_REALM": str(auth.get("realm", "")),
        "KEYCLOAK_AUDIENCE": str(auth.get("audience", "")),
        "KEYCLOAK_FRONTEND_CLIENT_ID": str(
            auth.get("frontendClientId", "")
        ),
        "KEYCLOAK_BACKEND_CLIENT_ID": str(
            auth.get("adminClientId", auth.get("audience", ""))
        ),
        "STACK_NAME": str(stack["name"]),
        "STACK_FAMILY": str(stack["family"]),
        "STACK_ROLE": str(stack["role"]),
        "PRIMARY_SERVICE": str(stack["primaryService"]),
        "DB_TYPE": str(database["type"]),
        "IMAGE_NAME": str(image["name"]),
    }


__all__ = [
    "DEPLOYMENT_KEYS",
    "DEPLOYMENT_KEY_SET",
    "DIGEST_IMAGE_PATTERN",
    "DIRECT_SECRET_KEYS",
    "ExecutableProfileError",
    "FALSE_DEBUG_KEYS",
    "IMAGE_PATTERN",
    "MEMORY_PATTERN",
    "NAME_PATTERN",
    "SECRET_PATTERN",
    "SEMVER_PATTERN",
    "config_path",
    "fixed_deployment_values",
    "load_json",
    "mapping",
    "read_env",
    "require_keys",
    "sequence",
    "text",
]
