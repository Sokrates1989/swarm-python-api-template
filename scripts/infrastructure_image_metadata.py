"""
Module: infrastructure_image_metadata.py

Description:
    Reads a platform-specific OCI image configuration from a registry and
    extracts a product release from trusted labels or official-image
    environment fields. This lets an operator identify an older immutable
    digest even after recent registry tags no longer point to it.

Dependencies:
    - Python standard library.
    - registry_image_tool.py for read-only authenticated registry access.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from collections.abc import Mapping

from registry_image_tool import (
    DistributionClient,
    MANIFEST_ACCEPT,
    RegistryToolError,
    normalize_repository,
)


def _platform_text(value: object) -> str:
    """Format an OCI descriptor platform for exact selection.

    Args:
        value: Possible platform mapping from an image-index descriptor.

    Returns:
        Slash-delimited platform text, or an empty string when invalid.
    """

    if not isinstance(value, Mapping):
        return ""
    operating_system = value.get("os")
    architecture = value.get("architecture")
    if not isinstance(operating_system, str) or not isinstance(architecture, str):
        return ""
    variant = value.get("variant")
    suffix = f"/{variant}" if isinstance(variant, str) and variant else ""
    return f"{operating_system}/{architecture}{suffix}"


def _json_mapping(body: bytes, description: str) -> Mapping[str, object]:
    """Decode one registry response as a JSON object.

    Args:
        body: Registry response bytes.
        description: Operator-safe response description.

    Returns:
        Decoded mapping.

    Raises:
        RegistryToolError: If the response is not a JSON object.
    """

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise RegistryToolError(
            f"Registry {description} response was not JSON."
        ) from error
    if not isinstance(payload, Mapping):
        raise RegistryToolError(f"Registry {description} response was not an object.")
    return payload


def _image_configuration(
    repository: str,
    reference: str,
    platform: str,
) -> Mapping[str, object]:
    """Load one immutable image's platform-specific OCI configuration.

    Args:
        repository: Normalized image repository.
        reference: Exact tag or digest.
        platform: Required OCI platform.

    Returns:
        Platform image configuration mapping.

    Raises:
        RegistryToolError: If index, manifest, platform, or config is absent.
    """

    client = DistributionClient(normalize_repository(repository))
    repository_path = urllib.parse.quote(client.location.repository, safe="/")
    encoded_reference = urllib.parse.quote(reference, safe=":._-")
    manifest_url = (
        f"{client.location.api_base}/v2/{repository_path}/manifests/"
        f"{encoded_reference}"
    )
    body, _ = client._open(manifest_url, MANIFEST_ACCEPT)
    manifest = _json_mapping(body, "manifest")
    descriptors = manifest.get("manifests")
    if isinstance(descriptors, list):
        descriptor = next(
            (
                item
                for item in descriptors
                if isinstance(item, Mapping)
                and _platform_text(item.get("platform")) == platform
            ),
            None,
        )
        digest = descriptor.get("digest") if isinstance(descriptor, Mapping) else None
        if not isinstance(digest, str):
            raise RegistryToolError(f"Image index does not contain {platform}.")
        encoded_digest = urllib.parse.quote(digest, safe=":")
        child_url = (
            f"{client.location.api_base}/v2/{repository_path}/manifests/"
            f"{encoded_digest}"
        )
        body, _ = client._open(child_url, MANIFEST_ACCEPT)
        manifest = _json_mapping(body, "platform manifest")
    config = manifest.get("config")
    digest = config.get("digest") if isinstance(config, Mapping) else None
    if not isinstance(digest, str):
        raise RegistryToolError("Image manifest has no configuration digest.")
    encoded_digest = urllib.parse.quote(digest, safe=":")
    config_url = f"{client.location.api_base}/v2/{repository_path}/blobs/{encoded_digest}"
    body, _ = client._open(config_url)
    return _json_mapping(body, "image configuration")


def release_version_from_config(
    configuration: Mapping[str, object], identifier: str
) -> str | None:
    """Extract a product release from trusted OCI labels or environment data.

    Args:
        configuration: Platform-specific image configuration.
        identifier: Stable infrastructure identifier.

    Returns:
        Numeric product version, or ``None`` when the image does not expose one.
    """

    runtime = configuration.get("config")
    if not isinstance(runtime, Mapping):
        return None
    labels = runtime.get("Labels")
    environment = runtime.get("Env")
    values: list[str] = []
    if isinstance(labels, Mapping):
        for key in ("org.opencontainers.image.version", "version"):
            value = labels.get(key)
            if isinstance(value, str):
                values.append(value)
    preferred_keys = {
        "postgres": ("PG_VERSION", "PG_MAJOR"),
        "redis": ("REDIS_VERSION",),
        "pgadmin": ("PGADMIN_VERSION",),
    }.get(identifier, ())
    if isinstance(environment, list):
        pairs = {
            item.split("=", 1)[0]: item.split("=", 1)[1]
            for item in environment
            if isinstance(item, str) and "=" in item
        }
        values.extend(pairs[key] for key in preferred_keys if key in pairs)
    for value in values:
        match = re.search(
            r"(?<![0-9])v?([0-9]+(?:\.[0-9]+){0,2})(?![0-9])",
            value,
        )
        if match is not None:
            return match.group(1)
    return None


def release_version_from_image(
    repository: str,
    reference: str,
    platform: str,
    identifier: str,
) -> str | None:
    """Resolve one immutable image and extract its declared product release.

    Args:
        repository: Normalized image repository.
        reference: Exact tag or digest.
        platform: Required OCI platform.
        identifier: Stable infrastructure identifier.

    Returns:
        Numeric product version, or ``None`` when metadata is absent.

    Raises:
        RegistryToolError: If registry evidence cannot be loaded safely.
    """

    configuration = _image_configuration(repository, reference, platform)
    return release_version_from_config(configuration, identifier)


__all__ = ["release_version_from_config", "release_version_from_image"]
