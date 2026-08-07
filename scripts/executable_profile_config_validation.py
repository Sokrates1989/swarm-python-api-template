"""
Module: executable_profile_config_validation.py

Description:
    Validates tracked schema-5 executable site configuration. The module
    enforces safe public URLs, exact Keycloak identity, service consistency,
    immutable image declarations, and secret identifier boundaries without
    containing any application-specific values.

Dependencies:
    - Python standard library.
    - scripts/executable_profile_support.py.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Mapping
from pathlib import PurePosixPath
from urllib.parse import urlparse

from executable_profile_keycloak_validation import validate_keycloak_auth
from executable_profile_release_validation import validate_release_coordination
from executable_profile_support import (
    DIGEST_IMAGE_PATTERN,
    IMAGE_PATTERN,
    NAME_PATTERN,
    SECRET_PATTERN,
    SEMVER_PATTERN,
    ExecutableProfileError,
    mapping,
    require_keys,
    sequence,
    text,
)


TRACKED_IMAGE_TAG_PATTERN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}")


def validate_https(value: str, field: str) -> None:
    """Require one non-local absolute HTTPS URL.

    Args:
        value: Candidate URL.
        field: Diagnostic field name.

    Raises:
        ExecutableProfileError: If the URL is unsafe for production.
    """

    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ExecutableProfileError(f"{field} must be an absolute HTTPS URL.")
    if parsed.username or parsed.password:
        raise ExecutableProfileError(f"{field} must not contain credentials.")
    if parsed.query or parsed.fragment:
        raise ExecutableProfileError(
            f"{field} must not contain query or fragment."
        )
    hostname = parsed.hostname.lower()
    if (
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", hostname)
        or ".." in hostname
    ):
        raise ExecutableProfileError(
            f"{field} contains an unsafe hostname."
        )
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ExecutableProfileError(f"{field} must not use a local host.")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
    ):
        raise ExecutableProfileError(
            f"{field} must not use a private or non-routable address."
        )
    if "*" in value or ".invalid" in value:
        raise ExecutableProfileError(f"{field} must not contain placeholders.")


def validate_origin(value: str, field: str) -> None:
    """Require one exact HTTPS origin without a path.

    Args:
        value: Candidate browser origin.
        field: Diagnostic field name.

    Raises:
        ExecutableProfileError: If the value is not an exact public origin.
    """

    validate_https(value, field)
    if urlparse(value).path not in {"", "/"}:
        raise ExecutableProfileError(f"{field} must not contain a path.")


def validate_domain(value: object, field: str, base_url: str) -> None:
    """Require a plain public hostname matching its declared base URL.

    Args:
        value: Candidate domain field.
        field: Diagnostic field name.
        base_url: Validated public base URL.

    Raises:
        ExecutableProfileError: If the hostname is malformed or drifts.
    """

    domain = text(value, field)
    hostname = urlparse(base_url).hostname
    if (
        hostname is None
        or "://" in domain
        or "/" in domain
        or "*" in domain
        or domain.lower() != hostname.lower()
    ):
        raise ExecutableProfileError(
            f"{field} must be the hostname from its public base URL."
        )


def validate_port(value: object, field: str) -> None:
    """Require one TCP port in the inclusive range 1 through 65535.

    Args:
        value: Candidate numeric value.
        field: Diagnostic field name.

    Raises:
        ExecutableProfileError: If the value is not a valid TCP port.
    """

    if isinstance(value, bool):
        raise ExecutableProfileError(f"{field} must be a TCP port.")
    try:
        port = int(str(value))
    except ValueError as error:
        raise ExecutableProfileError(f"{field} must be a TCP port.") from error
    if port < 1 or port > 65535:
        raise ExecutableProfileError(f"{field} must be between 1 and 65535.")


def _validate_redirect_uri(value: str, field: str) -> None:
    """Validate one exact Web or custom-scheme OIDC callback.

    Args:
        value: Candidate redirect URI.
        field: Diagnostic field name.

    Raises:
        ExecutableProfileError: If the callback is broad, local, or malformed.
    """

    if "*" in value or ".invalid" in value:
        raise ExecutableProfileError(
            f"{field} must be exact and non-placeholder."
        )
    parsed = urlparse(value)
    if parsed.scheme == "https":
        validate_https(value, field)
        return
    if (
        not re.fullmatch(r"[a-z][a-z0-9+.-]*", parsed.scheme)
        or parsed.scheme in {"http", "file"}
        or not parsed.path.startswith("/")
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ExecutableProfileError(
            f"{field} must be HTTPS or an exact custom-scheme callback."
        )


def _validate_release_image(
    image: Mapping[str, object],
    field: str,
) -> None:
    """Validate one immutable-version release image declaration.

    Args:
        image: Image mapping.
        field: Diagnostic field name.

    Raises:
        ExecutableProfileError: If repository or version policy is unsafe.
    """

    require_keys(
        image,
        {"name", "defaultVersion", "mutableTagsAllowed"},
        field,
    )
    name = text(image["name"], f"{field}.name")
    version = text(image["defaultVersion"], f"{field}.defaultVersion")
    if not IMAGE_PATTERN.fullmatch(name) or "/" not in name:
        raise ExecutableProfileError(
            f"{field}.name must be a registry repository."
        )
    if not SEMVER_PATTERN.fullmatch(version):
        raise ExecutableProfileError(
            f"{field}.defaultVersion must be semantic version."
        )
    if image["mutableTagsAllowed"] is not False:
        raise ExecutableProfileError(
            f"{field}.mutableTagsAllowed must be false."
        )


def _validate_database(
    data: Mapping[str, object],
    services: Mapping[str, object],
) -> None:
    """Validate database service declarations and pinned images.

    Args:
        data: Full site profile.
        services: Validated services mapping.

    Raises:
        ExecutableProfileError: If database type, mode, or image drifts.
    """

    database = mapping(data["database"], "database")
    require_keys(
        database,
        {"type", "defaultMode", "allowedModes"},
        "database",
    )
    database_type = text(database["type"], "database.type")
    allowed_modes = {
        text(mode, f"database.allowedModes[{index}]")
        for index, mode in enumerate(
            sequence(database["allowedModes"], "database.allowedModes")
        )
    }
    if database_type == "none":
        if services.get("database") is True or allowed_modes != {"none"}:
            raise ExecutableProfileError(
                "database.type=none requires services.database=false and mode none."
            )
    elif database_type == "postgresql":
        if services.get("database") is not True:
            raise ExecutableProfileError(
                "PostgreSQL profiles require services.database=true."
            )
        if not allowed_modes or not allowed_modes <= {"local", "external"}:
            raise ExecutableProfileError(
                "PostgreSQL modes must be local and/or external."
            )
    else:
        raise ExecutableProfileError(
            "Executable profiles currently support postgresql or none."
        )
    if database["defaultMode"] not in sequence(
        database["allowedModes"],
        "database.allowedModes",
    ):
        raise ExecutableProfileError("database.defaultMode must be allowed.")
    _validate_tracked_image(database, "image", "imageTrackTag", "database")
    _validate_tracked_image(
        database,
        "pgadminImage",
        "pgadminImageTrackTag",
        "database",
    )
    _validate_tracked_image(
        services,
        "redisImage",
        "redisImageTrackTag",
        "services",
    )


def _validate_tracked_image(
    container: Mapping[str, object],
    image_field: str,
    track_field: str,
    parent_field: str,
) -> None:
    """Validate a digest pin and its explicit safe update channel.

    The tag is audit metadata only. Runtime rendering continues to use the
    immutable digest, so checking for a refresh can never silently move a
    stateful service or cross a database major version.

    Args:
        container: Database or service mapping.
        image_field: Digest-pinned image field name.
        track_field: Registry tag used solely for update comparison.
        parent_field: Diagnostic parent path.

    Raises:
        ExecutableProfileError: If pin and channel are incomplete or unsafe.
    """

    has_image = image_field in container
    has_track = track_field in container
    if has_image != has_track:
        raise ExecutableProfileError(
            f"{parent_field}.{image_field} and {parent_field}.{track_field} "
            "must be declared together."
        )
    if not has_image:
        return
    if not DIGEST_IMAGE_PATTERN.fullmatch(
        text(container[image_field], f"{parent_field}.{image_field}")
    ):
        raise ExecutableProfileError(
            f"{parent_field}.{image_field} must be digest-pinned."
        )
    tag = text(container[track_field], f"{parent_field}.{track_field}")
    if not TRACKED_IMAGE_TAG_PATTERN.fullmatch(tag):
        raise ExecutableProfileError(
            f"{parent_field}.{track_field} must be one exact registry tag."
        )


def _validate_storage(data: Mapping[str, object]) -> None:
    """Validate an optional recommended production data-root path.

    Missing or empty ``storage.dataRoot`` deliberately means that the shared
    setup should use the current deployment checkout as its default.

    Args:
        data: Full site profile.

    Raises:
        ExecutableProfileError: If a non-empty profile default is not a safe,
            specific absolute POSIX host path.
    """

    storage = mapping(data.get("storage", {}), "storage")
    value = storage.get("dataRoot", "")
    if value == "":
        return
    data_root = text(value, "storage.dataRoot")
    parsed = PurePosixPath(data_root)
    if (
        not parsed.is_absolute()
        or data_root == "/"
        or not re.fullmatch(r"/[A-Za-z0-9._/-]+", data_root)
        or "//" in data_root
        or ".." in parsed.parts
    ):
        raise ExecutableProfileError(
            "storage.dataRoot must be empty or a specific absolute host path."
        )


def _validate_secret_declarations(data: Mapping[str, object]) -> None:
    """Validate required, optional, and base-mounted secret identifiers.

    Args:
        data: Site profile containing identifier-only secret declarations.

    Raises:
        ExecutableProfileError: If names overlap, drift, or are unsafe.
    """

    required = [
        text(value, f"secrets[{index}]")
        for index, value in enumerate(sequence(data["secrets"], "secrets"))
    ]
    optional = [
        text(value, f"optionalSecrets[{index}]")
        for index, value in enumerate(
            sequence(data.get("optionalSecrets", []), "optionalSecrets")
        )
    ]
    if any(not SECRET_PATTERN.fullmatch(value) for value in required + optional):
        raise ExecutableProfileError("Docker secret identifiers are unsafe.")
    if (
        len(required) != len(set(required))
        or len(optional) != len(set(optional))
        or set(required) & set(optional)
    ):
        raise ExecutableProfileError(
            "Required and optional Docker secret identifiers must be unique."
        )
    mounted_names = [
        text(
            mapping(raw_mount, f"secretMounts[{index}]").get("name"),
            f"secretMounts[{index}].name",
        )
        for index, raw_mount in enumerate(
            sequence(data["secretMounts"], "secretMounts")
        )
    ]
    if set(mounted_names) - set(required):
        raise ExecutableProfileError(
            "Base secret mounts must be declared in required secrets."
        )


def _editable_secret_value_names(data: Mapping[str, object]) -> set[str]:
    """Return exact profile secrets eligible for manual file import.

    Args:
        data: Executable site profile containing secret declarations.

    Returns:
        Required, optional, capability, and pgAdmin secret names excluding
        Keycloak client credentials owned by verified reconciliation.
    """

    names = {
        str(value)
        for value in (
            *sequence(data["secrets"], "secrets"),
            *sequence(data.get("optionalSecrets", []), "optionalSecrets"),
        )
    }
    keycloak_names: set[str] = set()
    mounts = list(sequence(data["secretMounts"], "secretMounts"))
    capabilities = mapping(data.get("capabilities", {}), "capabilities")
    for capability_name, raw_capability in capabilities.items():
        capability = mapping(
            raw_capability,
            f"capabilities.{capability_name}",
        )
        mounts.extend(
            sequence(
                capability.get("secretMounts", []),
                f"capabilities.{capability_name}.secretMounts",
            )
        )
    for index, raw_mount in enumerate(mounts):
        mount = mapping(raw_mount, f"secretMounts[{index}]")
        name = str(mount.get("name", ""))
        names.add(name)
        if mount.get("envKey") in {
            "KEYCLOAK_ADMIN_CLIENT_SECRET_FILE",
            "KEYCLOAK_CLIENT_SECRET_FILE",
        }:
            keycloak_names.add(name)
    database = mapping(data["database"], "database")
    pgadmin_secret = str(database.get("pgadminSecret", ""))
    if pgadmin_secret:
        names.add(pgadmin_secret)
    return {name for name in names - keycloak_names if name}


def _validate_secret_value_help(
    data: Mapping[str, object],
    config: Mapping[str, object],
) -> None:
    """Validate config-driven guidance for generated secret values files.

    Args:
        data: Full executable site profile.
        config: Validated ``secretsConfig`` mapping.

    Raises:
        ExecutableProfileError: If guidance is unsafe, references an
            unavailable secret, or is incomplete without a static template.
    """

    editable = _editable_secret_value_names(data)
    value_help = mapping(config.get("valueHelp", {}), "secretsConfig.valueHelp")
    names = set(value_help)
    unknown = sorted(names - editable)
    if unknown:
        raise ExecutableProfileError(
            "secretsConfig.valueHelp references non-editable secrets: "
            + ", ".join(unknown)
        )
    for name, raw_help in value_help.items():
        if not SECRET_PATTERN.fullmatch(name):
            raise ExecutableProfileError(
                f"secretsConfig.valueHelp contains an unsafe key: {name}"
            )
        help_text = text(raw_help, f"secretsConfig.valueHelp.{name}")
        if "\n" in help_text or "\r" in help_text:
            raise ExecutableProfileError(
                f"secretsConfig.valueHelp.{name} must be one line."
            )
    if "template" not in config:
        missing = sorted(editable - names)
        if missing:
            raise ExecutableProfileError(
                "Generated secret-file workflow requires value help for: "
                + ", ".join(missing)
            )


def _validate_secret_naming_policy(data: Mapping[str, object]) -> None:
    """Require an explicit exact-name policy for executable profiles.

    Args:
        data: Site profile containing ``secretsConfig``.

    Raises:
        ExecutableProfileError: If names would be implicitly prefixed or an
            optional template path could escape the repository.
    """

    config = mapping(data["secretsConfig"], "secretsConfig")
    require_keys(config, {"prefixed"}, "secretsConfig")
    if config["prefixed"] is not False:
        raise ExecutableProfileError(
            "Executable profiles require secretsConfig.prefixed=false."
        )
    _validate_secret_value_help(data, config)
    if "template" not in config:
        return
    template = text(config["template"], "secretsConfig.template")
    path = PurePosixPath(template)
    if (
        path.is_absolute()
        or ".." in path.parts
        or not re.fullmatch(r"[A-Za-z0-9._/-]+", template)
    ):
        raise ExecutableProfileError(
            "secretsConfig.template must be a safe repository-relative path."
        )


def _validate_keycloak_auth(auth: Mapping[str, object]) -> None:
    """Delegate Keycloak policy to its focused validator.

    Args:
        auth: Profile authentication mapping.

    Raises:
        ExecutableProfileError: If public OIDC identity is incomplete or unsafe.
    """

    validate_keycloak_auth(
        auth,
        validate_https=validate_https,
        validate_origin=validate_origin,
        validate_redirect_uri=_validate_redirect_uri,
    )


def _validate_routing(
    data: Mapping[str, object],
    services: Mapping[str, object],
) -> None:
    """Validate API and optional WebApp public routing declarations.

    Args:
        data: Full site profile.
        services: Validated services mapping.

    Raises:
        ExecutableProfileError: If routes, ports, or images are unsafe.
    """

    routing = mapping(data["routing"], "routing")
    require_keys(
        routing,
        {"containerPort", "apiBaseUrl", "domain", "healthPath"},
        "routing",
    )
    api_url = text(routing["apiBaseUrl"], "routing.apiBaseUrl")
    validate_https(api_url, "routing.apiBaseUrl")
    validate_domain(routing["domain"], "routing.domain", api_url)
    validate_port(routing["containerPort"], "routing.containerPort")
    constraint_label = str(
        routing.get("traefikConstraintLabel", "traefik-public")
    )
    if not NAME_PATTERN.fullmatch(constraint_label):
        raise ExecutableProfileError(
            "routing.traefikConstraintLabel must be a safe label value."
        )
    health_path = text(routing["healthPath"], "routing.healthPath")
    if not health_path.startswith("/") or health_path.startswith("/api/"):
        raise ExecutableProfileError(
            "routing.healthPath must be a relative API-service route."
        )
    if services.get("web") is not True:
        return
    required = (
        "webBaseUrl",
        "webDomain",
        "webContainerPort",
        "webHealthPath",
    )
    for field in required:
        if field not in routing:
            raise ExecutableProfileError(
                f"routing.{field} is required for WebApp."
            )
    web_url = text(routing["webBaseUrl"], "routing.webBaseUrl")
    validate_https(web_url, "routing.webBaseUrl")
    validate_domain(routing["webDomain"], "routing.webDomain", web_url)
    validate_port(routing["webContainerPort"], "routing.webContainerPort")
    if not text(
        routing["webHealthPath"],
        "routing.webHealthPath",
    ).startswith("/"):
        raise ExecutableProfileError(
            "routing.webHealthPath must begin with '/'."
        )
    web = mapping(data.get("web"), "web")
    require_keys(web, {"image", "resources"}, "web")
    _validate_release_image(mapping(web["image"], "web.image"), "web.image")


def validate_config(data: Mapping[str, object]) -> None:
    """Validate the reusable executable site-config contract.

    Args:
        data: Parsed profile.

    Raises:
        ExecutableProfileError: If required sections or public values are unsafe.
    """

    require_keys(
        data,
        {
            "version",
            "appId",
            "name",
            "renderer",
            "stack",
            "exposure",
            "routing",
            "database",
            "services",
            "image",
            "resources",
            "cors",
            "environment",
            "envKeys",
            "secrets",
            "secretsConfig",
            "secretMounts",
            "health",
        },
        "profile",
    )
    if str(data["version"]) != "5.0":
        raise ExecutableProfileError(
            "Executable site profiles require version 5.0."
        )
    renderer = mapping(data["renderer"], "renderer")
    if renderer.get("type") != "executable" or renderer.get("strict") is not True:
        raise ExecutableProfileError(
            "Executable profiles require renderer.type=executable and strict=true."
        )
    if not NAME_PATTERN.fullmatch(text(data["appId"], "appId")):
        raise ExecutableProfileError("appId is unsafe.")
    stack = mapping(data["stack"], "stack")
    require_keys(
        stack,
        {"family", "role", "primaryService", "name"},
        "stack",
    )
    if not NAME_PATTERN.fullmatch(text(stack["name"], "stack.name")):
        raise ExecutableProfileError("stack.name is unsafe.")
    services = mapping(data["services"], "services")
    if services.get("api") is not True:
        raise ExecutableProfileError(
            "Executable API profiles require services.api=true."
        )
    _validate_routing(data, services)
    validate_release_coordination(data, services)
    _validate_release_image(mapping(data["image"], "image"), "image")
    _validate_database(data, services)
    _validate_storage(data)
    cors = mapping(data["cors"], "cors")
    for index, origin in enumerate(sequence(cors["origins"], "cors.origins")):
        validate_origin(
            text(origin, f"cors.origins[{index}]"),
            f"cors.origins[{index}]",
        )
    _validate_secret_declarations(data)
    _validate_secret_naming_policy(data)
    auth = mapping(data.get("auth", {"provider": "none"}), "auth")
    if auth.get("provider") == "keycloak":
        _validate_keycloak_auth(auth)


__all__ = [
    "validate_config",
    "validate_domain",
    "validate_https",
    "validate_origin",
    "validate_port",
]
