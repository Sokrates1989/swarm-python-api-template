"""Typed sanitized evidence models for Felix Swarm release operations.

The models contain only public identities, hashes, paths, boolean checks, and
state transitions suitable for mode-0600 JSON receipts. They never accept or
serialize credential values or application database content.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ImageIdentity:
    """Describe one locally verified immutable registry image.

    Attributes:
        tag_reference: Semantic-version image reference selected by the profile.
        digest_reference: Registry repository plus immutable SHA-256 digest.
        digest: Bare registry SHA-256 digest.
        version: OCI image version label.
        revision: OCI source-revision label.
        dependency_lock_sha256: Optional API dependency-lock label.
        architecture: Image CPU architecture.
        operating_system: Image operating system.
        component: Public component role (`api` or `web`).
        profile_fingerprint: Optional WebApp production-profile fingerprint.
    """

    tag_reference: str
    digest_reference: str
    digest: str
    version: str
    revision: str
    dependency_lock_sha256: str | None
    architecture: str
    operating_system: str
    component: str = "api"
    profile_fingerprint: str | None = None

    def as_dict(self) -> dict[str, str]:
        """Serialize public immutable image evidence.

        Returns:
            JSON-ready image identity mapping.
        """

        payload = {
            "component": self.component,
            "tagReference": self.tag_reference,
            "digestReference": self.digest_reference,
            "digest": self.digest,
            "version": self.version,
            "revision": self.revision,
            "architecture": self.architecture,
            "operatingSystem": self.operating_system,
        }
        if self.dependency_lock_sha256 is not None:
            payload["dependencyLockSha256"] = self.dependency_lock_sha256
        if self.profile_fingerprint is not None:
            payload["profileFingerprint"] = self.profile_fingerprint
        return payload


@dataclass(frozen=True)
class BackupEvidence:
    """Describe a verified pre-deployment database backup.

    Attributes:
        kind: ``pg-dump`` or ``initial-empty-database``.
        path: Protected host backup path.
        sha256: SHA-256 of the retained backup or empty-state declaration.
        size_bytes: Backup artifact size.
        verified: Whether structural verification passed.
    """

    kind: str
    path: Path
    sha256: str
    size_bytes: int
    verified: bool

    def as_dict(self) -> dict[str, Any]:
        """Serialize backup metadata without database content.

        Returns:
            JSON-ready backup evidence mapping.
        """

        return {
            "kind": self.kind,
            "path": str(self.path),
            "sha256": self.sha256,
            "sizeBytes": self.size_bytes,
            "verified": self.verified,
        }


@dataclass(frozen=True)
class PreviousDeployment:
    """Capture candidate-only state needed for rollback.

    Attributes:
        stack_exists: Whether the candidate stack existed before deploy.
        service_exists: Whether the candidate API service existed.
        image_reference: Prior API image tag/digest, if any.
        image_digest: Prior API immutable digest when inspectable.
        web_service_exists: Whether the candidate WebApp service existed.
        web_image_reference: Prior WebApp image tag/digest, if any.
        web_image_digest: Prior WebApp immutable digest when inspectable.
    """

    stack_exists: bool
    service_exists: bool
    image_reference: str | None
    image_digest: str | None
    web_service_exists: bool = False
    web_image_reference: str | None = None
    web_image_digest: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Serialize prior candidate deployment identity.

        Returns:
            JSON-ready prior state mapping.
        """

        return {
            "stackExists": self.stack_exists,
            "serviceExists": self.service_exists,
            "imageReference": self.image_reference,
            "imageDigest": self.image_digest,
            "webServiceExists": self.web_service_exists,
            "webImageReference": self.web_image_reference,
            "webImageDigest": self.web_image_digest,
        }


@dataclass(frozen=True)
class PreflightEvidence:
    """Aggregate strict, secret-free candidate preflight results.

    Attributes:
        profile_fingerprint: Validated site-profile SHA-256.
        image: Resolved immutable API image identity.
        stack_path: Exact generated digest-bound stack path.
        docker_secret_names: Verified external Docker secret identifiers.
        data_directories: Verified candidate host directories.
        checks: Named successful preflight checks.
        web_image: Resolved immutable WebApp image identity.
    """

    profile_fingerprint: str
    image: ImageIdentity
    stack_path: Path
    docker_secret_names: tuple[str, ...]
    data_directories: tuple[str, ...]
    checks: dict[str, bool]
    web_image: ImageIdentity | None = None

    def as_dict(self) -> dict[str, Any]:
        """Serialize sanitized preflight evidence.

        Returns:
            JSON-ready preflight result.
        """

        images = {"api": self.image.as_dict()}
        if self.web_image is not None:
            images["web"] = self.web_image.as_dict()
        return {
            "profileFingerprint": self.profile_fingerprint,
            "images": images,
            "stackPath": str(self.stack_path),
            "dockerSecretNames": list(self.docker_secret_names),
            "dataDirectories": list(self.data_directories),
            "checks": dict(sorted(self.checks.items())),
        }


@dataclass(frozen=True)
class HealthEvidence:
    """Represent strict post-deployment health outcomes.

    Attributes:
        checks: Named strict boolean checks.
        service_images: Deployed service image references.
        api_health_fingerprint: SHA-256 of sanitized API health fields.
        log_scan_lines: Number of recent API log lines scanned.
        web_metadata_fingerprint: Optional SHA-256 of public WebApp metadata.
    """

    checks: dict[str, bool]
    service_images: dict[str, str]
    api_health_fingerprint: str
    log_scan_lines: int
    web_metadata_fingerprint: str | None = None

    @property
    def healthy(self) -> bool:
        """Return whether every required health check passed.

        Returns:
            True only when all named checks are true.
        """

        return bool(self.checks) and all(self.checks.values())

    def as_dict(self) -> dict[str, Any]:
        """Serialize sanitized strict health evidence.

        Returns:
            JSON-ready health result.
        """

        payload = {
            "healthy": self.healthy,
            "checks": dict(sorted(self.checks.items())),
            "serviceImages": dict(sorted(self.service_images.items())),
            "apiHealthFingerprint": self.api_health_fingerprint,
            "logScanLines": self.log_scan_lines,
        }
        if self.web_metadata_fingerprint is not None:
            payload["webMetadataFingerprint"] = self.web_metadata_fingerprint
        return payload


@dataclass
class ReleaseReceipt:
    """Build a sanitized release state-machine receipt.

    Attributes:
        operation_id: Unique public operation identifier.
        started_at: UTC start timestamp.
        state: Current terminal/intermediate state.
        preflight: Optional strict preflight evidence.
        previous: Optional prior candidate deployment identity.
        backup: Optional verified backup evidence.
        health: Optional strict health evidence.
        rollback: Sanitized rollback result details.
        events: Ordered public state transition labels.
    """

    operation_id: str
    started_at: str
    state: str = "created"
    preflight: PreflightEvidence | None = None
    previous: PreviousDeployment | None = None
    backup: BackupEvidence | None = None
    health: HealthEvidence | None = None
    rollback: dict[str, Any] | None = None
    events: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Serialize the receipt without credential or application data.

        Returns:
            JSON-ready state-machine receipt.
        """

        return {
            "schemaVersion": 2,
            "kind": "felix-swarm-release-receipt",
            "operationId": self.operation_id,
            "startedAt": self.started_at,
            "state": self.state,
            "preflight": self.preflight.as_dict() if self.preflight else None,
            "previous": self.previous.as_dict() if self.previous else None,
            "backup": self.backup.as_dict() if self.backup else None,
            "health": self.health.as_dict() if self.health else None,
            "rollback": self.rollback,
            "events": list(self.events),
        }
