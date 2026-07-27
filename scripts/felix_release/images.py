"""Resolve and verify immutable Felix WebApp and API registry images.

The resolver accepts only the public semantic tags selected by the validated
deployment profile, then binds each to one unique linux/amd64 registry digest
and its component-specific OCI identity labels.
"""

from __future__ import annotations

import json
import re
from typing import Any

from felix_site_contract import FelixSiteProfile
from felix_web_stack import web_image_reference

from .command import CommandRunner
from .errors import FelixReleaseError
from .models import ImageIdentity


_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_WEB_ORIGIN = "https://felix-app.fe-wi.com"
_API_ORIGIN = "https://api.felix-app.fe-wi.com"
_ISSUER = "https://keycloak.fe-wi.com/realms/felix-new"


def _inspect_published_image(
    runner: CommandRunner,
    tag_reference: str,
    component: str,
) -> tuple[dict[str, Any], dict[str, str], str, str, str]:
    """Pull and inspect one unique digest-backed registry image.

    Args:
        runner: Shell-free command runner.
        tag_reference: Selected semantic-version image reference.
        component: Human-readable component used in diagnostics.

    Returns:
        Image object, label mapping, digest reference, digest, and version.

    Raises:
        FelixReleaseError: If inspect JSON, digest identity, or platform fails.

    Side Effects:
        Pulls the selected image into the local Docker cache.
    """

    runner.run(["docker", "pull", tag_reference])
    result = runner.run(["docker", "image", "inspect", tag_reference])
    try:
        inspected = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise FelixReleaseError(f"Invalid {component} image inspect JSON.") from exc
    if not isinstance(inspected, list) or len(inspected) != 1:
        raise FelixReleaseError(
            f"Docker {component} inspect did not return one image."
        )
    image = inspected[0]
    repository, version = tag_reference.rsplit(":", 1)
    repo_digests = [
        str(value)
        for value in image.get("RepoDigests", [])
        if str(value).startswith(f"{repository}@sha256:")
    ]
    if len(repo_digests) != 1:
        raise FelixReleaseError(
            f"Published {component} image has no unique registry digest."
        )
    digest_reference = repo_digests[0]
    digest = digest_reference.split("@", 1)[1]
    if not _DIGEST_PATTERN.fullmatch(digest):
        raise FelixReleaseError(f"Published {component} digest is invalid.")
    if image.get("Architecture") != "amd64" or image.get("Os") != "linux":
        raise FelixReleaseError(f"Felix {component} platform must be linux/amd64.")
    labels = image.get("Config", {}).get("Labels", {})
    if not isinstance(labels, dict):
        raise FelixReleaseError(f"Published {component} labels are invalid.")
    return image, labels, digest_reference, digest, version


def resolve_image_identity(
    runner: CommandRunner,
    profile: FelixSiteProfile,
) -> ImageIdentity:
    """Resolve the API tag and require exact Felix backend OCI labels.

    Args:
        runner: Shell-free command runner.
        profile: Validated Felix candidate profile.

    Returns:
        Verified immutable API image identity.

    Raises:
        FelixReleaseError: If API labels or source hashes drift.
    """

    tag_reference = profile.image_reference
    image, labels, digest_reference, digest, version = _inspect_published_image(
        runner,
        tag_reference,
        "API",
    )
    revision = str(labels.get("org.opencontainers.image.revision", ""))
    lock_hash = str(labels.get("com.fe-wi.dependency-lock-sha256", ""))
    if (
        labels.get("org.opencontainers.image.version") != version
        or labels.get("com.fe-wi.app-profile") != "felix"
        or labels.get("com.fe-wi.backend-app-id") != "felix"
        or not _REVISION_PATTERN.fullmatch(revision)
        or not _HASH_PATTERN.fullmatch(lock_hash)
    ):
        raise FelixReleaseError("Published Felix API labels are invalid.")
    return ImageIdentity(
        tag_reference,
        digest_reference,
        digest,
        version,
        revision,
        lock_hash,
        str(image["Architecture"]),
        str(image["Os"]),
    )


def _web_labels_match(labels: dict[str, str], version: str) -> bool:
    """Check exact public Felix WebApp OCI labels.

    Args:
        labels: Docker image label mapping.
        version: Selected semantic image version.

    Returns:
        True only when all public identities match.
    """

    expected = {
        "org.opencontainers.image.version": version,
        "com.felicitas_wisdom.app.id": "felix",
        "com.felicitas_wisdom.profile.environment": "production",
        "com.felicitas_wisdom.web.origin": _WEB_ORIGIN,
        "com.felicitas_wisdom.backend.origin": _API_ORIGIN,
        "com.felicitas_wisdom.keycloak.issuer": _ISSUER,
        "com.felicitas_wisdom.keycloak.realm": "felix-new",
        "com.felicitas_wisdom.keycloak.client_id": "felix-new-frontend",
    }
    return all(labels.get(key) == value for key, value in expected.items())


def resolve_web_image_identity(
    runner: CommandRunner,
    profile: FelixSiteProfile,
) -> ImageIdentity:
    """Resolve the WebApp tag and require exact public profile OCI labels.

    Args:
        runner: Shell-free command runner.
        profile: Validated Felix candidate profile.

    Returns:
        Verified immutable WebApp image identity.

    Raises:
        FelixReleaseError: If WebApp labels or source hashes drift.
    """

    tag_reference = web_image_reference(profile)
    image, labels, digest_reference, digest, version = _inspect_published_image(
        runner,
        tag_reference,
        "WebApp",
    )
    revision = str(labels.get("org.opencontainers.image.revision", ""))
    fingerprint = str(
        labels.get("com.felicitas_wisdom.profile.fingerprint", "")
    )
    if (
        not _REVISION_PATTERN.fullmatch(revision)
        or not _HASH_PATTERN.fullmatch(fingerprint)
        or not _web_labels_match(labels, version)
    ):
        raise FelixReleaseError("Published Felix WebApp labels are invalid.")
    return ImageIdentity(
        tag_reference,
        digest_reference,
        digest,
        version,
        revision,
        None,
        str(image["Architecture"]),
        str(image["Os"]),
        component="web",
        profile_fingerprint=fingerprint,
    )
