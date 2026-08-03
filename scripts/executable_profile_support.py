"""
Module: executable_profile_support.py

Description:
    Defines shared constants, errors, strict JSON/dotenv parsing, and fixed
    application identity derivation for schema-5 executable deployment
    profiles. Operator-selected deployment values such as stack names,
    domains, image repositories, and Keycloak deployment identity are
    deliberately excluded from immutable application identity. These helpers
    contain no application identity and perform no runtime mutation.

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
    r"[1-9][0-9]*(?:B|[KMGTP](?:B|iB)?)",
    re.IGNORECASE,
)


def memory_limit_is_unlimited(value: str) -> bool:
    """Return whether a deployment memory value omits the Docker constraint.

    Args:
        value: Operator or profile memory-limit value.

    Returns:
        Whether the case-insensitive value is ``unlimited`` or ``0``.
    """

    return value.strip().lower() in {"unlimited", "0"}


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
    "KEYCLOAK_REALM_DISPLAY_NAME",
    "KEYCLOAK_REALM_ENABLED",
    "KEYCLOAK_REGISTRATION_ALLOWED",
    "KEYCLOAK_RESET_PASSWORD_ALLOWED",
    "KEYCLOAK_REMEMBER_ME",
    "KEYCLOAK_VERIFY_EMAIL",
    "KEYCLOAK_LOGIN_WITH_EMAIL_ALLOWED",
    "KEYCLOAK_LOGIN_THEME",
    "KEYCLOAK_ACCOUNT_THEME",
    "KEYCLOAK_ADMIN_THEME",
    "KEYCLOAK_EMAIL_THEME",
    "KEYCLOAK_INTERNATIONALIZATION_ENABLED",
    "KEYCLOAK_SUPPORTED_LOCALES",
    "KEYCLOAK_DEFAULT_LOCALE",
    "KEYCLOAK_EMAIL_SENDER_ENABLED",
    "KEYCLOAK_SMTP_FROM",
    "KEYCLOAK_SMTP_FROM_DISPLAY_NAME",
    "KEYCLOAK_SMTP_REPLY_TO",
    "KEYCLOAK_SMTP_REPLY_TO_DISPLAY_NAME",
    "KEYCLOAK_SMTP_ENVELOPE_FROM",
    "KEYCLOAK_SMTP_HOST",
    "KEYCLOAK_SMTP_PORT",
    "KEYCLOAK_SMTP_STARTTLS",
    "KEYCLOAK_SMTP_SSL",
    "KEYCLOAK_SMTP_AUTH",
    "KEYCLOAK_SMTP_USERNAME",
    "KEYCLOAK_BOOTSTRAP_TEST_USERS_ENABLED",
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
    "TRAEFIK_CONSTRAINT_LABEL",
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

# Keycloak identity selected per deployment; the server URL is intentionally
# absent because it remains the tracked administrator-credential trust anchor.
KEYCLOAK_DEPLOYMENT_KEYS = frozenset(
    {
        "KEYCLOAK_ISSUER_URL",
        "KEYCLOAK_REALM",
        "KEYCLOAK_REALM_DISPLAY_NAME",
        "KEYCLOAK_REALM_ENABLED",
        "KEYCLOAK_REGISTRATION_ALLOWED",
        "KEYCLOAK_RESET_PASSWORD_ALLOWED",
        "KEYCLOAK_REMEMBER_ME",
        "KEYCLOAK_VERIFY_EMAIL",
        "KEYCLOAK_LOGIN_WITH_EMAIL_ALLOWED",
        "KEYCLOAK_LOGIN_THEME",
        "KEYCLOAK_ACCOUNT_THEME",
        "KEYCLOAK_ADMIN_THEME",
        "KEYCLOAK_EMAIL_THEME",
        "KEYCLOAK_INTERNATIONALIZATION_ENABLED",
        "KEYCLOAK_SUPPORTED_LOCALES",
        "KEYCLOAK_DEFAULT_LOCALE",
        "KEYCLOAK_EMAIL_SENDER_ENABLED",
        "KEYCLOAK_SMTP_FROM",
        "KEYCLOAK_SMTP_FROM_DISPLAY_NAME",
        "KEYCLOAK_SMTP_REPLY_TO",
        "KEYCLOAK_SMTP_REPLY_TO_DISPLAY_NAME",
        "KEYCLOAK_SMTP_ENVELOPE_FROM",
        "KEYCLOAK_SMTP_HOST",
        "KEYCLOAK_SMTP_PORT",
        "KEYCLOAK_SMTP_STARTTLS",
        "KEYCLOAK_SMTP_SSL",
        "KEYCLOAK_SMTP_AUTH",
        "KEYCLOAK_SMTP_USERNAME",
        "KEYCLOAK_BOOTSTRAP_TEST_USERS_ENABLED",
        "KEYCLOAK_AUDIENCE",
        "KEYCLOAK_FRONTEND_CLIENT_ID",
        "KEYCLOAK_BACKEND_CLIENT_ID",
    }
)

# Additive generated-environment fields accepted from pre-upgrade `.env` files.
OPTIONAL_DEPLOYMENT_DEFAULTS = {
    "KEYCLOAK_REALM_DISPLAY_NAME": "",
    "KEYCLOAK_REALM_ENABLED": "",
    "KEYCLOAK_REGISTRATION_ALLOWED": "",
    "KEYCLOAK_RESET_PASSWORD_ALLOWED": "",
    "KEYCLOAK_REMEMBER_ME": "",
    "KEYCLOAK_VERIFY_EMAIL": "",
    "KEYCLOAK_LOGIN_WITH_EMAIL_ALLOWED": "",
    "KEYCLOAK_LOGIN_THEME": "",
    "KEYCLOAK_ACCOUNT_THEME": "",
    "KEYCLOAK_ADMIN_THEME": "",
    "KEYCLOAK_EMAIL_THEME": "",
    "KEYCLOAK_INTERNATIONALIZATION_ENABLED": "",
    "KEYCLOAK_SUPPORTED_LOCALES": "",
    "KEYCLOAK_DEFAULT_LOCALE": "",
    "KEYCLOAK_EMAIL_SENDER_ENABLED": "",
    "KEYCLOAK_SMTP_FROM": "",
    "KEYCLOAK_SMTP_FROM_DISPLAY_NAME": "",
    "KEYCLOAK_SMTP_REPLY_TO": "",
    "KEYCLOAK_SMTP_REPLY_TO_DISPLAY_NAME": "",
    "KEYCLOAK_SMTP_ENVELOPE_FROM": "",
    "KEYCLOAK_SMTP_HOST": "",
    "KEYCLOAK_SMTP_PORT": "",
    "KEYCLOAK_SMTP_STARTTLS": "",
    "KEYCLOAK_SMTP_SSL": "",
    "KEYCLOAK_SMTP_AUTH": "",
    "KEYCLOAK_SMTP_USERNAME": "",
    "KEYCLOAK_BOOTSTRAP_TEST_USERS_ENABLED": "",
}

# Public root-environment keys corresponding to profile-owned realm settings.
KEYCLOAK_REALM_SETTING_ENV_KEYS = (
    ("enabled", "KEYCLOAK_REALM_ENABLED"),
    ("registrationAllowed", "KEYCLOAK_REGISTRATION_ALLOWED"),
    ("resetPasswordAllowed", "KEYCLOAK_RESET_PASSWORD_ALLOWED"),
    ("rememberMe", "KEYCLOAK_REMEMBER_ME"),
    ("verifyEmail", "KEYCLOAK_VERIFY_EMAIL"),
    ("loginWithEmailAllowed", "KEYCLOAK_LOGIN_WITH_EMAIL_ALLOWED"),
)

# Public deployment keys corresponding to profile-owned realm theme settings.
KEYCLOAK_THEME_ENV_KEYS = (
    ("login", "KEYCLOAK_LOGIN_THEME"),
    ("account", "KEYCLOAK_ACCOUNT_THEME"),
    ("admin", "KEYCLOAK_ADMIN_THEME"),
    ("email", "KEYCLOAK_EMAIL_THEME"),
)

# Public deployment keys corresponding to profile-owned localization settings.
KEYCLOAK_LOCALIZATION_ENV_KEYS = (
    ("enabled", "KEYCLOAK_INTERNATIONALIZATION_ENABLED"),
    ("supportedLocales", "KEYCLOAK_SUPPORTED_LOCALES"),
    ("defaultLocale", "KEYCLOAK_DEFAULT_LOCALE"),
)

# Public deployment keys corresponding to profile-owned SMTP sender settings.
KEYCLOAK_EMAIL_SENDER_ENV_KEYS = (
    ("enabled", "KEYCLOAK_EMAIL_SENDER_ENABLED"),
    ("from", "KEYCLOAK_SMTP_FROM"),
    ("fromDisplayName", "KEYCLOAK_SMTP_FROM_DISPLAY_NAME"),
    ("replyTo", "KEYCLOAK_SMTP_REPLY_TO"),
    ("replyToDisplayName", "KEYCLOAK_SMTP_REPLY_TO_DISPLAY_NAME"),
    ("envelopeFrom", "KEYCLOAK_SMTP_ENVELOPE_FROM"),
    ("host", "KEYCLOAK_SMTP_HOST"),
    ("port", "KEYCLOAK_SMTP_PORT"),
    ("startTls", "KEYCLOAK_SMTP_STARTTLS"),
    ("ssl", "KEYCLOAK_SMTP_SSL"),
    ("authentication", "KEYCLOAK_SMTP_AUTH"),
    ("username", "KEYCLOAK_SMTP_USERNAME"),
)


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
    for key, default in OPTIONAL_DEPLOYMENT_DEFAULTS.items():
        values.setdefault(key, default)
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


def _keycloak_deployment_defaults(
    auth: Mapping[str, object],
    provider: str,
) -> dict[str, str]:
    """Derive editable Keycloak defaults for one generated environment.

    Args:
        auth: Parsed authentication profile mapping.
        provider: Selected authentication provider.

    Returns:
        Complete Keycloak subset, empty for non-Keycloak providers.
    """

    enabled = provider == "keycloak"
    realm_settings = auth.get("realmSettings", {})
    normalized = realm_settings if isinstance(realm_settings, Mapping) else {}
    themes = auth.get("themes", {})
    normalized_themes = themes if isinstance(themes, Mapping) else {}
    localization = auth.get("localization", {})
    normalized_localization = (
        localization if isinstance(localization, Mapping) else {}
    )
    email_sender = auth.get("emailSender", {})
    normalized_email_sender = (
        email_sender if isinstance(email_sender, Mapping) else {}
    )
    values = {
        "KEYCLOAK_BASE_URL": str(auth.get("serverUrl", "")),
        "KEYCLOAK_ISSUER_URL": str(auth.get("issuerUrl", "")),
        "KEYCLOAK_REALM": str(auth.get("realm", "")),
        "KEYCLOAK_REALM_DISPLAY_NAME": str(auth.get("realmDisplayName", "")),
        "KEYCLOAK_BOOTSTRAP_TEST_USERS_ENABLED": (
            str(bool(auth.get("bootstrapTestUsersEnabled", False))).lower()
            if enabled
            else ""
        ),
        "KEYCLOAK_AUDIENCE": str(auth.get("audience", "")),
        "KEYCLOAK_FRONTEND_CLIENT_ID": str(auth.get("frontendClientId", "")),
        "KEYCLOAK_BACKEND_CLIENT_ID": str(
            auth.get("adminClientId", auth.get("audience", ""))
        ),
    }
    for setting_name, environment_key in KEYCLOAK_REALM_SETTING_ENV_KEYS:
        values[environment_key] = (
            str(bool(normalized.get(setting_name, False))).lower()
            if enabled
            else ""
        )
    for setting_name, environment_key in KEYCLOAK_THEME_ENV_KEYS:
        values[environment_key] = (
            str(normalized_themes.get(setting_name, "default"))
            if enabled
            else ""
        )
    configured_locales = normalized_localization.get("supportedLocales", [])
    localization_values = {
        "enabled": str(
            bool(normalized_localization.get("enabled", False))
        ).lower(),
        "supportedLocales": ",".join(
            str(locale) for locale in configured_locales
        ),
        "defaultLocale": str(
            normalized_localization.get("defaultLocale", "")
        ),
    }
    for setting_name, environment_key in KEYCLOAK_LOCALIZATION_ENV_KEYS:
        values[environment_key] = (
            localization_values[setting_name] if enabled else ""
        )
    email_boolean_fields = {"enabled", "startTls", "ssl", "authentication"}
    for setting_name, environment_key in KEYCLOAK_EMAIL_SENDER_ENV_KEYS:
        raw_value = normalized_email_sender.get(setting_name, "")
        serialized = (
            str(bool(raw_value)).lower()
            if setting_name in email_boolean_fields
            else str(raw_value)
        )
        values[environment_key] = serialized if enabled else ""
    return values


def fixed_deployment_values(
    data: Mapping[str, object],
    config_id: str,
) -> dict[str, str]:
    """Derive profile defaults for application and authentication identity.

    Args:
        data: Parsed site profile.
        config_id: Selected site-config ID.

    Returns:
        Profile-derived public root environment defaults. Deployment-instance
        choices such as stack names, domains, image repositories, ports, and
        resources are omitted. Keycloak values remain present as editable
        defaults and are filtered by :func:`immutable_deployment_values` when
        enforcing application identity.
    """

    stack = mapping(data["stack"], "stack")
    database = mapping(data["database"], "database")
    environment = mapping(data["environment"], "environment")
    auth = mapping(data.get("auth", {"provider": "none"}), "auth")
    provider = str(auth.get("provider", "none"))
    values = {
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
        "STACK_FAMILY": str(stack["family"]),
        "STACK_ROLE": str(stack["role"]),
        "PRIMARY_SERVICE": str(stack["primaryService"]),
        "DB_TYPE": str(database["type"]),
    }
    values.update(_keycloak_deployment_defaults(auth, provider))
    return values


def immutable_deployment_values(
    data: Mapping[str, object],
    config_id: str,
) -> dict[str, str]:
    """Return site-profile identity that one deployment may not override.

    Args:
        data: Parsed site profile.
        config_id: Selected site-config ID.

    Returns:
        Application, renderer, and service identity excluding editable
        Keycloak deployment values.
    """

    return {
        key: value
        for key, value in fixed_deployment_values(data, config_id).items()
        if key not in KEYCLOAK_DEPLOYMENT_KEYS
    }


__all__ = [
    "DEPLOYMENT_KEYS",
    "DEPLOYMENT_KEY_SET",
    "DIGEST_IMAGE_PATTERN",
    "DIRECT_SECRET_KEYS",
    "ExecutableProfileError",
    "FALSE_DEBUG_KEYS",
    "IMAGE_PATTERN",
    "KEYCLOAK_DEPLOYMENT_KEYS",
    "KEYCLOAK_EMAIL_SENDER_ENV_KEYS",
    "KEYCLOAK_LOCALIZATION_ENV_KEYS",
    "KEYCLOAK_REALM_SETTING_ENV_KEYS",
    "KEYCLOAK_THEME_ENV_KEYS",
    "MEMORY_PATTERN",
    "NAME_PATTERN",
    "SECRET_PATTERN",
    "SEMVER_PATTERN",
    "config_path",
    "fixed_deployment_values",
    "immutable_deployment_values",
    "load_json",
    "mapping",
    "memory_limit_is_unlimited",
    "read_env",
    "require_keys",
    "sequence",
    "text",
]
