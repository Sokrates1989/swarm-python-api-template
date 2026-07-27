"""
Module: felix_site_contract.py

Description:
    Loads the versioned Felix Swarm site profile, binds it to the validated
    candidate-production public profile, and resolves executable environment
    and Docker secret declarations before rendering may begin.

Dependencies:
    - Python 3.10 or newer standard library.
    - scripts/release_profile.py.

"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from release_profile import (
    SwarmReleaseProfile,
    SwarmReleaseProfileError,
    load_release_profile,
)
from felix_site_runtime import (
    build_profile_fingerprint,
    build_release_environment_values,
)


_SCHEMA_VERSION = "4.0"
_SITE_PROFILE_NAME = "felix.json"
_EXPECTED_TOP_LEVEL_KEYS = frozenset(
    {
        "$schema",
        "version",
        "appId",
        "name",
        "description",
        "kind",
        "renderer",
        "stack",
        "exposure",
        "routing",
        "database",
        "services",
        "image",
        "resources",
        "storage",
        "cors",
        "auth",
        "environment",
        "envKeys",
        "secrets",
        "optionalSecrets",
        "secretsConfig",
        "secretMounts",
        "capabilities",
        "health",
    }
)
_EXPECTED_CAPABILITIES = ("aiChat", "webPush")
_CANDIDATE_API_ORIGIN = "https://api.felix-app.fe-wi.com"
_CANDIDATE_WEB_ORIGIN = "https://felix-app.fe-wi.com"
_CANDIDATE_REALM = "felix-new"
_CANDIDATE_FRONTEND_CLIENT = "felix-new-frontend"
_CANDIDATE_BACKEND_CLIENT = "felix-new-backend"
_CANDIDATE_STACK = "felix-new"
_APP_IMAGE = "sokrates1989/python-api-felix"
_SEMANTIC_VERSION_PATTERN = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z.-]+)?"
)
_DIGEST_IMAGE_PATTERN = re.compile(r"[a-z0-9][a-z0-9._/-]*@sha256:[a-f0-9]{64}")
_SECRET_NAME_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{2,127}")
_MARKER_PATTERN = re.compile(r"\$\{[^}]*\}|XXX_CHANGE|###[A-Za-z0-9_]")
_DIRECT_SECRET_ENV_KEYS = frozenset(
    {
        "ADMIN_API_KEY",
        "AI_CHAT_API_KEY",
        "BACKUP_DELETE_API_KEY",
        "BACKUP_RESTORE_API_KEY",
        "DATABASE_URL",
        "DB_PASSWORD",
        "KEYCLOAK_ADMIN_CLIENT_SECRET",
        "KEYCLOAK_CLIENT_SECRET",
        "WEB_PUSH_VAPID_PRIVATE_KEY",
    }
)
_FALSE_ENV_KEYS = frozenset(
    {
        "AI_CHAT_DEBUG_ENABLED",
        "AI_CHAT_DEBUG_INCLUDE_PROMPTS",
        "DEBUG",
        "DEBUG_ENABLED",
        "ENABLE_HTTP_DEBUG_LOGGING",
        "LOG_REQUEST_BODY",
        "LOG_REQUEST_HEADERS",
        "LOG_RESPONSE_BODY",
        "LOG_RESPONSE_HEADERS",
        "SQL_ECHO_ENABLED",
    }
)
_LOCAL_PUBLIC_HOSTS = frozenset(
    {"0.0.0.0", "10.0.2.2", "127.0.0.1", "host.docker.internal", "localhost"}
)


class FelixSiteProfileError(ValueError):
    """Reports malformed, unsafe, unresolved, or drifting Felix site input."""


@dataclass(frozen=True)
class SecretMount:
    """Describes one Docker secret mounted into one API file setting.

    Attributes:
        name: External Docker secret identifier.
        env_key: API setting that receives the mounted file path.
        target: Absolute path below `/run/secrets`.
    """

    name: str
    env_key: str
    target: str


@dataclass(frozen=True)
class FelixSiteProfile:
    """Contains one validated executable Felix deployment profile.

    Attributes:
        path: Canonical tracked JSON profile path.
        data: Parsed, validated public profile object.
        deployment: Validated wizard-generated deployment-instance values.
        environment: Active non-secret API environment mapping.
        env_keys: Canonical executable environment-key order.
        secret_mounts: Active base and capability-selected secret mounts.
        image_reference: Immutable Felix release image reference.
        fingerprint: SHA-256 of canonical public site-profile JSON.
        active_capabilities: Enabled optional capability names.
    """

    path: Path
    data: Mapping[str, object]
    deployment: Mapping[str, str]
    environment: Mapping[str, str]
    env_keys: tuple[str, ...]
    secret_mounts: tuple[SecretMount, ...]
    image_reference: str
    fingerprint: str
    active_capabilities: tuple[str, ...]

    def safe_summary(self) -> dict[str, object]:
        """Build non-secret validation and rendering evidence.

        Returns:
            Public app/schema/image identity, field names, Docker secret names,
            active capabilities, and deterministic profile fingerprint.
        """

        secret_names = [mount.name for mount in self.secret_mounts]
        if self.deployment["PGADMIN_ENABLED"] == "true":
            database = _as_mapping(self.data["database"], "database")
            secret_names.append(str(database["pgadminSecret"]))
        return {
            "appId": "felix",
            "schemaVersion": _SCHEMA_VERSION,
            "imageReference": self.image_reference,
            "environmentFieldNames": list(self.env_keys),
            "dockerSecretNames": secret_names,
            "activeCapabilities": list(self.active_capabilities),
            "deploymentFieldNames": list(self.deployment),
            "profileFingerprint": self.fingerprint,
        }


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Build a JSON object while rejecting duplicate keys.

    Args:
        pairs: Ordered key/value pairs supplied by `json.loads`.

    Returns:
        Duplicate-free JSON object.

    Raises:
        FelixSiteProfileError: If a key appears more than once.
    """

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise FelixSiteProfileError(f"Duplicate JSON key is forbidden: {key}")
        result[key] = value
    return result


def _as_mapping(value: object, field: str) -> Mapping[str, object]:
    """Require one JSON object.

    Args:
        value: Parsed JSON value.
        field: Field path used in diagnostics.

    Returns:
        Validated mapping.

    Raises:
        FelixSiteProfileError: If the value is not a JSON object.
    """

    if not isinstance(value, dict):
        raise FelixSiteProfileError(f"{field} must be a JSON object.")
    return value


def _as_list(value: object, field: str) -> list[object]:
    """Require one JSON array.

    Args:
        value: Parsed JSON value.
        field: Field path used in diagnostics.

    Returns:
        Validated mutable list.

    Raises:
        FelixSiteProfileError: If the value is not a JSON array.
    """

    if not isinstance(value, list):
        raise FelixSiteProfileError(f"{field} must be a JSON array.")
    return value


def _as_text(value: object, field: str) -> str:
    """Require one non-empty, edge-trimmed JSON string.

    Args:
        value: Parsed JSON value.
        field: Field path used in diagnostics.

    Returns:
        Validated text.

    Raises:
        FelixSiteProfileError: If the value is empty, non-text, or untrimmed.
    """

    if not isinstance(value, str) or not value or value != value.strip():
        raise FelixSiteProfileError(f"{field} must be non-empty trimmed text.")
    return value


def _as_bool(value: object, field: str) -> bool:
    """Require one JSON boolean.

    Args:
        value: Parsed JSON value.
        field: Field path used in diagnostics.

    Returns:
        Validated boolean.

    Raises:
        FelixSiteProfileError: If the value is not a JSON boolean.
    """

    if not isinstance(value, bool):
        raise FelixSiteProfileError(f"{field} must be a JSON boolean.")
    return value


def _read_site_profile(path: Path) -> dict[str, object]:
    """Read strict UTF-8 JSON with duplicate-key detection.

    Args:
        path: Canonical tracked Felix profile path.

    Returns:
        Parsed root JSON object.

    Raises:
        FelixSiteProfileError: If the file is absent, malformed, duplicated,
            non-UTF-8, or not a root JSON object.
        OSError: If another filesystem read failure occurs.
    """

    if not path.is_file():
        raise FelixSiteProfileError(f"Felix site profile is missing: {path}")
    try:
        content = path.read_text(encoding="utf-8")
        if _MARKER_PATTERN.search(content):
            raise FelixSiteProfileError(
                f"{path} contains an unresolved placeholder marker."
            )
        parsed = json.loads(content, object_pairs_hook=_reject_duplicate_pairs)
    except UnicodeDecodeError as error:
        raise FelixSiteProfileError(f"{path} must be valid UTF-8.") from error
    except json.JSONDecodeError as error:
        raise FelixSiteProfileError(f"{path} contains invalid JSON: {error}") from error
    return dict(_as_mapping(parsed, "root"))


def _require_exact_keys(
    value: Mapping[str, object],
    expected: set[str] | frozenset[str],
    field: str,
) -> None:
    """Require an exact JSON object schema.

    Args:
        value: Object whose keys are validated.
        expected: Complete allowed and required key set.
        field: Field path used in diagnostics.

    Returns:
        None when keys match.

    Raises:
        FelixSiteProfileError: If keys are missing or unknown.
    """

    actual = set(value)
    if actual == set(expected):
        return
    missing = sorted(set(expected) - actual)
    unknown = sorted(actual - set(expected))
    details = []
    if missing:
        details.append("missing " + ", ".join(missing))
    if unknown:
        details.append("unknown " + ", ".join(unknown))
    raise FelixSiteProfileError(f"{field} keys are invalid: {'; '.join(details)}")


def _require_value(actual: object, expected: object, field: str) -> None:
    """Require one exact fixed-contract value.

    Args:
        actual: Value read from the site profile.
        expected: Approved fixed value.
        field: Field path used in diagnostics.

    Returns:
        None when values match.

    Raises:
        FelixSiteProfileError: If the profile drifts from the contract.
    """

    if actual != expected:
        raise FelixSiteProfileError(f"{field} must equal {expected!r}.")


def _validate_public_https(value: str, field: str) -> None:
    """Validate one credential-free public HTTPS URL.

    Args:
        value: Absolute URL to validate.
        field: Field path used in diagnostics.

    Returns:
        None for a public HTTPS URL.

    Raises:
        FelixSiteProfileError: If the URL is wildcarded, local, credentialed,
            malformed, or unresolved.
    """

    parsed = urlsplit(value)
    hostname = (parsed.hostname or "").casefold()
    if parsed.scheme != "https" or not hostname:
        raise FelixSiteProfileError(f"{field} must be an absolute HTTPS URL.")
    if parsed.username is not None or parsed.password is not None:
        raise FelixSiteProfileError(f"{field} must not contain credentials.")
    if hostname in _LOCAL_PUBLIC_HOSTS or hostname.endswith((".local", ".internal")):
        raise FelixSiteProfileError(f"{field} must not use a local endpoint.")
    if "*" in value or _MARKER_PATTERN.search(value):
        raise FelixSiteProfileError(f"{field} must not contain wildcard/placeholder text.")


def _parse_secret_mounts(value: object, field: str) -> tuple[SecretMount, ...]:
    """Parse and validate Docker secret mount declarations.

    Args:
        value: JSON array of secret mount objects.
        field: Field path used in diagnostics.

    Returns:
        Ordered immutable secret mount declarations.

    Raises:
        FelixSiteProfileError: If names, file fields, targets, or uniqueness
            violate the Docker secret boundary.
    """

    mounts: list[SecretMount] = []
    for index, raw_mount in enumerate(_as_list(value, field)):
        item_field = f"{field}[{index}]"
        mount = _as_mapping(raw_mount, item_field)
        _require_exact_keys(mount, {"name", "envKey", "target"}, item_field)
        name = _as_text(mount["name"], f"{item_field}.name")
        env_key = _as_text(mount["envKey"], f"{item_field}.envKey")
        target = _as_text(mount["target"], f"{item_field}.target")
        if not _SECRET_NAME_PATTERN.fullmatch(name):
            raise FelixSiteProfileError(f"{item_field}.name is not a safe identifier.")
        if not env_key.endswith("_FILE") or env_key in _DIRECT_SECRET_ENV_KEYS:
            raise FelixSiteProfileError(f"{item_field}.envKey must be file-backed.")
        if target != f"/run/secrets/{name}":
            raise FelixSiteProfileError(
                f"{item_field}.target must equal /run/secrets/{name}."
            )
        mounts.append(SecretMount(name=name, env_key=env_key, target=target))
    if len({mount.name for mount in mounts}) != len(mounts):
        raise FelixSiteProfileError(f"{field} contains duplicate Docker secret names.")
    if len({mount.env_key for mount in mounts}) != len(mounts):
        raise FelixSiteProfileError(f"{field} contains duplicate secret file fields.")
    return tuple(mounts)


def _validate_stack_and_database(data: Mapping[str, object]) -> None:
    """Validate candidate stack identity and local PostgreSQL selection.

    Args:
        data: Parsed root site profile.

    Returns:
        None when stack and database values match.

    Raises:
        FelixSiteProfileError: If identity, mode, or digest policy drifts.
    """

    stack = _as_mapping(data["stack"], "stack")
    _require_exact_keys(stack, {"family", "role", "primaryService", "name"}, "stack")
    expected_stack = {
        "family": "api",
        "role": "full-stack",
        "primaryService": "api",
        "name": _CANDIDATE_STACK,
    }
    for key, expected in expected_stack.items():
        _require_value(stack[key], expected, f"stack.{key}")

    database = _as_mapping(data["database"], "database")
    _require_exact_keys(
        database,
        {
            "type",
            "defaultMode",
            "allowedModes",
            "image",
            "pgadminImage",
            "pgadminSecret",
        },
        "database",
    )
    _require_value(database["type"], "postgresql", "database.type")
    _require_value(database["defaultMode"], "local", "database.defaultMode")
    _require_value(
        database["allowedModes"],
        ["local", "external"],
        "database.allowedModes",
    )
    image = _as_text(database["image"], "database.image")
    if not _DIGEST_IMAGE_PATTERN.fullmatch(image):
        raise FelixSiteProfileError("database.image must be pinned by SHA-256 digest.")
    pgadmin_image = _as_text(database["pgadminImage"], "database.pgadminImage")
    if not _DIGEST_IMAGE_PATTERN.fullmatch(pgadmin_image):
        raise FelixSiteProfileError(
            "database.pgadminImage must be pinned by SHA-256 digest."
        )
    pgadmin_secret = _as_text(database["pgadminSecret"], "database.pgadminSecret")
    if not _SECRET_NAME_PATTERN.fullmatch(pgadmin_secret):
        raise FelixSiteProfileError("database.pgadminSecret is invalid.")


def _validate_metadata_and_exposure(data: Mapping[str, object]) -> None:
    """Validate human metadata, public exposure, and secret-template policy.

    Args:
        data: Parsed root site profile.

    Returns:
        None when descriptive and adapter metadata is complete.

    Raises:
        FelixSiteProfileError: If metadata is empty or exposure/template policy
            could bypass the fixed candidate renderer.
    """

    _as_text(data["name"], "name")
    _as_text(data["description"], "description")
    exposure = _as_mapping(data["exposure"], "exposure")
    expected_exposure = {
        "type": "public",
        "publicDomainRequired": True,
        "traefik": True,
        "publishedPorts": True,
    }
    _require_value(exposure, expected_exposure, "exposure")
    secrets_config = _as_mapping(data["secretsConfig"], "secretsConfig")
    expected_secrets_config = {
        "template": "setup/templates/secrets.felix.env.template",
        "prefixed": False,
    }
    _require_value(secrets_config, expected_secrets_config, "secretsConfig")


def _validate_services_and_routing(data: Mapping[str, object]) -> None:
    """Validate required services and exact candidate API routing.

    Args:
        data: Parsed root site profile.

    Returns:
        None when services, digest, port, host, and network match.

    Raises:
        FelixSiteProfileError: If a service or route is unsafe or drifting.
    """

    services = _as_mapping(data["services"], "services")
    _require_exact_keys(
        services,
        {"api", "redis", "database", "redisImage"},
        "services",
    )
    for service in ("api", "redis", "database"):
        _require_value(services[service], True, f"services.{service}")
    redis_image = _as_text(services["redisImage"], "services.redisImage")
    if not _DIGEST_IMAGE_PATTERN.fullmatch(redis_image):
        raise FelixSiteProfileError("services.redisImage must be pinned by SHA-256 digest.")

    routing = _as_mapping(data["routing"], "routing")
    routing_expected = {
        "containerPort": 8080,
        "apiBaseUrl": _CANDIDATE_API_ORIGIN,
        "domain": "api.felix-app.fe-wi.com",
        "healthPath": "/health",
        "traefikNetwork": "traefik-public",
        "sslMode": "proxy",
    }
    _require_exact_keys(routing, set(routing_expected), "routing")
    for key, expected in routing_expected.items():
        _require_value(routing[key], expected, f"routing.{key}")
    _validate_public_https(str(routing["apiBaseUrl"]), "routing.apiBaseUrl")


def _validate_resources_and_health(data: Mapping[str, object]) -> None:
    """Validate bounded resources, storage ownership, and health assertions.

    Args:
        data: Parsed root site profile.

    Returns:
        None when resource, storage, and health values match.

    Raises:
        FelixSiteProfileError: If any fixed value is malformed or drifting.
    """

    resources = _as_mapping(data["resources"], "resources")
    _require_exact_keys(resources, {"defaultReplicas", "defaultMemoryLimit"}, "resources")
    _require_value(resources["defaultReplicas"], 1, "resources.defaultReplicas")
    if not re.fullmatch(r"[1-9][0-9]*(?:M|G)", str(resources["defaultMemoryLimit"])):
        raise FelixSiteProfileError("resources.defaultMemoryLimit is invalid.")
    storage = _as_mapping(data["storage"], "storage")
    _require_exact_keys(storage, {"dataRoot"}, "storage")
    _require_value(storage["dataRoot"], "/swarm/volumes/felix-new", "storage.dataRoot")
    health = _as_mapping(data["health"], "health")
    _require_exact_keys(health, {"path", "expected"}, "health")
    _require_value(health["path"], "/health", "health.path")
    expected_health = {
        "appId": "felix",
        "appProfile": "felix",
        "dataProfile": "postgresql",
        "authProvider": "keycloak",
        "startup": "ok",
    }
    _require_value(health["expected"], expected_health, "health.expected")


def _validate_fixed_sections(data: Mapping[str, object]) -> None:
    """Validate all fixed non-secret Felix infrastructure sections.

    Args:
        data: Parsed root site profile.

    Returns:
        None when the complete fixed schema matches.

    Raises:
        FelixSiteProfileError: If schema or infrastructure identity drifts.
    """

    _require_exact_keys(data, _EXPECTED_TOP_LEVEL_KEYS, "root")
    fixed = {
        "$schema": "site-config-schema",
        "version": _SCHEMA_VERSION,
        "appId": "felix",
        "kind": "api",
        "renderer": {"type": "felix-production", "strict": True},
    }
    for key, expected in fixed.items():
        _require_value(data[key], expected, key)
    _validate_metadata_and_exposure(data)
    _validate_stack_and_database(data)
    _validate_services_and_routing(data)
    _validate_resources_and_health(data)


def _parse_secret_name_sets(
    data: Mapping[str, object],
    mounts: Sequence[SecretMount],
) -> set[str]:
    """Validate base and optional Docker secret name declarations.

    Args:
        data: Parsed root site profile.
        mounts: Required base secret mounts.

    Returns:
        Declared optional Docker secret-name set.

    Raises:
        FelixSiteProfileError: If names are unsafe or base mounts drift.
    """

    optional_items = [
        _as_text(value, "optionalSecrets[]")
        for value in _as_list(data["optionalSecrets"], "optionalSecrets")
    ]
    optional_names = set(optional_items)
    required_names = [
        _as_text(value, "secrets[]") for value in _as_list(data["secrets"], "secrets")
    ]
    if required_names != [mount.name for mount in mounts]:
        raise FelixSiteProfileError(
            "secrets must exactly match required base secret mount names."
        )
    if len(required_names) != len(set(required_names)):
        raise FelixSiteProfileError("secrets contains duplicate names.")
    if len(optional_items) != len(optional_names):
        raise FelixSiteProfileError("optionalSecrets contains duplicate names.")
    if set(required_names) & optional_names:
        raise FelixSiteProfileError("Required and optional Docker secrets must differ.")
    for name in (*required_names, *optional_names):
        if not _SECRET_NAME_PATTERN.fullmatch(name):
            raise FelixSiteProfileError(f"Invalid Docker secret identifier: {name}")
    return optional_names


def _parse_capability(
    capabilities: Mapping[str, object],
    name: str,
) -> tuple[bool, dict[str, str], tuple[SecretMount, ...]]:
    """Parse one optional capability declaration.

    Args:
        capabilities: Complete capability object.
        name: Capability key to parse.

    Returns:
        Enabled flag, safe public environment, and file-backed mounts.

    Raises:
        FelixSiteProfileError: If the capability schema or values are invalid.
    """

    field = f"capabilities.{name}"
    capability = _as_mapping(capabilities[name], field)
    _require_exact_keys(capability, {"enabled", "environment", "secretMounts"}, field)
    environment = {
        key: _as_text(value, f"{field}.environment.{key}")
        for key, value in _as_mapping(
            capability["environment"], f"{field}.environment"
        ).items()
    }
    if any(key in _DIRECT_SECRET_ENV_KEYS for key in environment):
        raise FelixSiteProfileError(f"{field} contains a direct secret field.")
    mounts = _parse_secret_mounts(capability["secretMounts"], f"{field}.secretMounts")
    return _as_bool(capability["enabled"], f"{field}.enabled"), environment, mounts


def _merge_capability_environment(
    target: dict[str, str],
    source: Mapping[str, str],
    name: str,
) -> None:
    """Merge enabled capability values without allowing collisions.

    Args:
        target: Active environment mutated in place.
        source: Capability environment values.
        name: Capability key used in diagnostics.

    Returns:
        None.

    Raises:
        FelixSiteProfileError: If a capability duplicates a base/active field.

    Side Effects:
        Adds non-colliding capability fields to `target`.
    """

    for key, value in source.items():
        if key in target:
            raise FelixSiteProfileError(
                f"capabilities.{name} duplicates environment key {key}."
            )
        target[key] = value


def _validate_mount_uniqueness(mounts: Sequence[SecretMount]) -> None:
    """Validate active Docker secret and file-field uniqueness.

    Args:
        mounts: Required plus enabled capability mounts.

    Returns:
        None when names and file fields are unique.

    Raises:
        FelixSiteProfileError: If an active mount collides.
    """

    if len({mount.name for mount in mounts}) != len(mounts):
        raise FelixSiteProfileError("Active capability Docker secret names collide.")
    if len({mount.env_key for mount in mounts}) != len(mounts):
        raise FelixSiteProfileError("Active capability secret file fields collide.")


def _active_inputs(
    data: Mapping[str, object],
) -> tuple[dict[str, str], tuple[SecretMount, ...], tuple[str, ...]]:
    """Resolve base plus enabled capability environment and secret mounts.

    Args:
        data: Parsed root site profile.

    Returns:
        Active environment, mounts, and capability names.

    Raises:
        FelixSiteProfileError: If declarations collide or escape file backing.
    """

    environment = {
        key: _as_text(value, f"environment.{key}")
        for key, value in _as_mapping(data["environment"], "environment").items()
    }
    mounts = list(_parse_secret_mounts(data["secretMounts"], "secretMounts"))
    optional_names = _parse_secret_name_sets(data, mounts)
    capabilities = _as_mapping(data["capabilities"], "capabilities")
    _require_exact_keys(capabilities, set(_EXPECTED_CAPABILITIES), "capabilities")
    declared_optional: set[str] = set()
    active_names: list[str] = []
    for name in _EXPECTED_CAPABILITIES:
        enabled, capability_environment, capability_mounts = _parse_capability(
            capabilities, name
        )
        declared_optional.update(mount.name for mount in capability_mounts)
        if enabled:
            active_names.append(name)
            _merge_capability_environment(environment, capability_environment, name)
            mounts.extend(capability_mounts)
    if declared_optional != optional_names:
        raise FelixSiteProfileError(
            "optionalSecrets must exactly match capability secret declarations."
        )
    if any(key in _DIRECT_SECRET_ENV_KEYS for key in environment):
        raise FelixSiteProfileError("Direct secret environment fields are forbidden.")
    _validate_mount_uniqueness(mounts)
    return environment, tuple(mounts), tuple(active_names)


def _apply_release_environment(
    environment: dict[str, str],
    release: SwarmReleaseProfile,
) -> None:
    """Overlay tracked defaults with validated deployment-instance values.

    Args:
        environment: Active public environment mutated in place.
        release: Validated wizard-generated deployment configuration.

    Returns:
        None.

    Side Effects:
        Replaces only deployment-owned keys already declared by the site
        profile.
    """

    for key, value in build_release_environment_values(release).items():
        if key not in environment:
            raise FelixSiteProfileError(
                f"environment.{key} is required for deployment overlay."
            )
        environment[key] = value


def _validate_environment_values(
    environment: Mapping[str, str],
    release: SwarmReleaseProfile,
) -> None:
    """Validate identity, debug policy, and capability endpoint safety.

    Args:
        environment: Active non-secret API environment.
        release: Validated wizard-generated deployment configuration.

    Returns:
        None when fixed values and production flags are safe.

    Raises:
        FelixSiteProfileError: If a value drifts or contains a placeholder.
    """

    for key, expected in build_release_environment_values(release).items():
        if environment.get(key) != expected:
            raise FelixSiteProfileError(f"environment.{key} must equal {expected!r}.")
    for key in _FALSE_ENV_KEYS:
        if environment.get(key) != "false":
            raise FelixSiteProfileError(f"environment.{key} must equal 'false'.")
    if environment.get("LOG_LEVEL", "").upper() == "DEBUG":
        raise FelixSiteProfileError("environment.LOG_LEVEL must not enable DEBUG.")
    for key, value in environment.items():
        if _MARKER_PATTERN.search(value):
            raise FelixSiteProfileError(f"environment.{key} contains a placeholder.")
    endpoint = environment.get("AI_CHAT_COMPLETIONS_ENDPOINT")
    if endpoint:
        _validate_public_https(endpoint, "environment.AI_CHAT_COMPLETIONS_ENDPOINT")


def _validate_environment(
    data: Mapping[str, object],
    environment: Mapping[str, str],
    mounts: tuple[SecretMount, ...],
    release: SwarmReleaseProfile,
) -> tuple[str, ...]:
    """Validate executable envKeys and production-safe API values.

    Args:
        data: Parsed root site profile.
        environment: Active non-secret environment.
        mounts: Active Docker secret file mappings.
        release: Validated wizard-generated deployment configuration.

    Returns:
        Canonical executable environment-key order.

    Raises:
        FelixSiteProfileError: If envKeys drifts from active executable fields.
    """

    env_keys = tuple(
        _as_text(value, "envKeys[]") for value in _as_list(data["envKeys"], "envKeys")
    )
    expected_keys = tuple(environment) + tuple(mount.env_key for mount in mounts)
    if env_keys != expected_keys or len(set(env_keys)) != len(env_keys):
        raise FelixSiteProfileError(
            "envKeys must exactly enumerate active environment and secret-file fields."
        )
    _validate_environment_values(environment, release)
    return env_keys


def _validate_image(
    data: Mapping[str, object],
    environment: Mapping[str, str],
    release: SwarmReleaseProfile,
) -> str:
    """Validate the Felix semantic release image policy.

    Args:
        data: Parsed root site profile.
        environment: Active environment containing the API image tag.
        release: Validated deployment image selection.

    Returns:
        Versioned Felix image reference.

    Raises:
        FelixSiteProfileError: If repository, tag, environment, or mutable-tag
            policy differs from the approved release image.
    """

    image = _as_mapping(data["image"], "image")
    _require_value(image["name"], _APP_IMAGE, "image.name")
    version = _as_text(image["defaultVersion"], "image.defaultVersion")
    if not _SEMANTIC_VERSION_PATTERN.fullmatch(version):
        raise FelixSiteProfileError("image.defaultVersion must be a semantic version.")
    _require_value(image["mutableTagsAllowed"], False, "image.mutableTagsAllowed")
    selected = release.values["IMAGE_VERSION"]
    if environment.get("IMAGE_TAG") != selected:
        raise FelixSiteProfileError(
            "environment.IMAGE_TAG must match the deployment image version."
        )
    return f"{_APP_IMAGE}:{selected}"


def load_felix_site_profile(root: Path) -> FelixSiteProfile:
    """Load and validate the fixed Felix site and operator public profiles.

    Args:
        root: Swarm repository root containing `.env` and `site-configs`.

    Returns:
        Fully validated executable Felix profile.

    Raises:
        FelixSiteProfileError: If site configuration is unsafe or drifting.
        SwarmReleaseProfileError: If `.env` is missing or invalid.
        OSError: If another filesystem read failure occurs.
    """

    # Lazy import avoids a module cycle while keeping identity validation
    # separately navigable and below this module's hard size limit.
    from felix_site_identity import validate_auth_and_cors

    resolved_root = root.resolve()
    release = load_release_profile(resolved_root)
    profile_path = resolved_root / "site-configs" / _SITE_PROFILE_NAME
    data = _read_site_profile(profile_path)
    _validate_fixed_sections(data)
    validate_auth_and_cors(data, release)
    environment, mounts, capabilities = _active_inputs(data)
    _apply_release_environment(environment, release)
    env_keys = _validate_environment(data, environment, mounts, release)
    image_reference = _validate_image(data, environment, release)
    return FelixSiteProfile(
        path=profile_path,
        data=data,
        deployment=release.values,
        environment=environment,
        env_keys=env_keys,
        secret_mounts=mounts,
        image_reference=image_reference,
        fingerprint=build_profile_fingerprint(data, release),
        active_capabilities=capabilities,
    )
