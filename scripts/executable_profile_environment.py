"""
Module: executable_profile_environment.py

Description:
    Builds operator-editable defaults and atomically writes the public root
    environment for any schema-5 executable site profile. Profile identity and
    service defaults are read exclusively from the selected site config.

Dependencies:
    - Python standard library.
    - Executable profile support and validation modules.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from pathlib import Path

from executable_profile_config_validation import validate_config
from executable_profile_deployment_validation import validate_deployment
from executable_profile_support import (
    DEPLOYMENT_KEYS,
    DEPLOYMENT_KEY_SET,
    ExecutableProfileError,
    config_path,
    fixed_deployment_values,
    load_json,
    mapping,
)


def default_deployment_values(
    data: Mapping[str, object],
    config_id: str,
) -> dict[str, str]:
    """Build fixed and operator-owned deployment defaults.

    Args:
        data: Parsed executable profile.
        config_id: Selected site-config ID.

    Returns:
        Complete generated root environment values.
    """

    values = fixed_deployment_values(data, config_id)
    routing = mapping(data["routing"], "routing")
    database = mapping(data["database"], "database")
    image = mapping(data["image"], "image")
    resources = mapping(data["resources"], "resources")
    storage = mapping(data["storage"], "storage")
    environment = mapping(data["environment"], "environment")
    services = mapping(data["services"], "services")
    cors = mapping(data["cors"], "cors")
    web = mapping(data.get("web", {}), "web")
    web_image = mapping(web.get("image", {}), "web.image")
    web_resources = mapping(web.get("resources", {}), "web.resources")
    pgadmin = mapping(data.get("pgadmin", {}), "pgadmin")
    web_enabled = bool(services.get("web", False))
    exposure = mapping(data["exposure"], "exposure")
    proxy_default = "traefik" if bool(exposure.get("traefik")) else "none"
    values.update(
        {
            "API_BASE_URL": str(routing["apiBaseUrl"]),
            "DOMAIN": str(routing["domain"]),
            "WEB_BASE_URL": (
                str(routing.get("webBaseUrl", "")) if web_enabled else ""
            ),
            "WEB_DOMAIN": (
                str(routing.get("webDomain", "")) if web_enabled else ""
            ),
            "CORS_ORIGINS": ",".join(
                str(item) for item in cors.get("origins", [])
            ),
            "STACK_NAME": str(mapping(data["stack"], "stack")["name"]),
            "DB_MODE": str(database["defaultMode"]),
            "DB_HOST": str(environment.get("DB_HOST", "postgres")),
            "DB_PORT": str(
                environment.get("DB_PORT", database.get("port", "5432"))
            ),
            "DB_NAME": str(environment.get("DB_NAME", data["appId"])),
            "DB_USER": str(environment.get("DB_USER", data["appId"])),
            "PROXY_TYPE": proxy_default,
            "SSL_MODE": str(routing.get("sslMode", "")),
            "TRAEFIK_NETWORK": str(routing.get("traefikNetwork", "")),
            "TRAEFIK_CONSTRAINT_LABEL": (
                str(
                    routing.get(
                        "traefikConstraintLabel",
                        "traefik-public",
                    )
                )
                if proxy_default == "traefik"
                else ""
            ),
            "TRAEFIK_CERT_RESOLVER": str(
                routing.get("traefikCertResolver", "le")
            ),
            "API_PUBLISHED_PORT": str(routing.get("publishedPort", "8083")),
            "WEB_PUBLISHED_PORT": str(
                routing.get("webPublishedPort", "8084")
            ),
            "PGADMIN_PUBLISHED_PORT": str(
                routing.get("pgadminPublishedPort", "5054")
            ),
            "IMAGE_NAME": str(image["name"]),
            "IMAGE_VERSION": str(image["defaultVersion"]),
            "API_REPLICAS": str(resources.get("defaultReplicas", 1)),
            "MEMORY_LIMIT": str(
                resources.get("defaultMemoryLimit", "512M")
            ),
            "DATA_ROOT": str(storage["dataRoot"]),
            "PGADMIN_ENABLED": str(pgadmin.get("enabled", False)).lower(),
            "PGADMIN_DOMAIN": str(pgadmin.get("domain", "")),
            "PGADMIN_EMAIL": str(pgadmin.get("email", "")),
            "PGADMIN_REPLICAS": (
                "1" if bool(pgadmin.get("enabled", False)) else "0"
            ),
            "WEB_ENABLED": str(web_enabled).lower(),
            "WEB_IMAGE_NAME": str(web_image.get("name", "")),
            "WEB_IMAGE_VERSION": str(web_image.get("defaultVersion", "")),
            "WEB_REPLICAS": str(web_resources.get("defaultReplicas", 1)),
            "WEB_MEMORY_LIMIT": str(
                web_resources.get(
                    "defaultMemoryLimit",
                    resources.get("defaultWebMemoryLimit", "128M"),
                )
            ),
        }
    )
    return values


def load_config_defaults(
    root: Path,
    config_id: str,
) -> tuple[Mapping[str, object], dict[str, str]]:
    """Load one selected profile and generate its setup defaults.

    Args:
        root: Repository root.
        config_id: Selected site-config ID.

    Returns:
        Parsed validated profile and complete default environment.

    Raises:
        ExecutableProfileError: If the profile is not executable or is unsafe.
    """

    selected_path = config_path(root.resolve(), config_id)
    data = load_json(selected_path)
    validate_config(data)
    return data, default_deployment_values(data, config_id)


def write_deployment_env(
    root: Path,
    config_id: str,
    overrides: Mapping[str, str],
    *,
    force: bool = False,
) -> Path:
    """Atomically write one public-only generated root environment.

    Args:
        root: Repository root.
        config_id: Selected site-config ID.
        overrides: Operator-selected dynamic values.
        force: Replace an existing root environment when true.

    Returns:
        Written root ``.env`` path.

    Raises:
        ExecutableProfileError: If an override is unknown, fixed, or invalid.
        FileExistsError: If the destination exists without ``force``.
        OSError: If the protected temporary file cannot be written or replaced.
    """

    resolved_root = root.resolve()
    data, values = load_config_defaults(resolved_root, config_id)
    fixed_keys = set(fixed_deployment_values(data, config_id))
    for key, value in overrides.items():
        if key not in DEPLOYMENT_KEY_SET:
            raise ExecutableProfileError(
                f"Unknown deployment override: {key}"
            )
        if key in fixed_keys and value != values[key]:
            raise ExecutableProfileError(
                f"Fixed site-config field cannot be overridden: {key}"
            )
        values[key] = value
    validate_deployment(data, config_id, values)
    destination = resolved_root / ".env"
    if destination.exists() and not force:
        raise FileExistsError(
            f"Refusing to replace existing environment: {destination}"
        )
    content = "\n".join(
        (
            "# Generated by the shared site-config setup wizard.",
            f"# Deployment profile: {config_id}",
            *(f"{key}={values[key]}" for key in DEPLOYMENT_KEYS),
            "",
        )
    )
    descriptor, temporary_name = tempfile.mkstemp(
        dir=resolved_root,
        prefix=".deployment-env.",
        suffix=".tmp",
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            newline="\n",
        ) as output:
            output.write(content)
        temporary.replace(destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return destination


__all__ = [
    "default_deployment_values",
    "load_config_defaults",
    "write_deployment_env",
]
