"""Felix-only deploy, health, receipt, rollback, and failure-drill machine.

The state machine sequences strict preflight, verified database evidence,
digest-bound deployment, public health, candidate-only rollback, and the
automatic-rollback/data-continuity drill. Every terminal path retains a
sanitized receipt when filesystem state permits.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from felix_site_contract import FelixSiteProfile, load_felix_site_profile

from .backup import (
    API_SERVICE,
    WEB_SERVICE,
    capture_previous_deployment,
    create_continuity_marker,
    create_verified_backup,
    verify_continuity_marker,
)
from .command import CommandRunner
from .errors import FelixReleaseError
from .health import SENSITIVE_LOG_PATTERN, run_strict_health
from .models import (
    HealthEvidence,
    ImageIdentity,
    PreflightEvidence,
    PreviousDeployment,
    ReleaseReceipt,
)
from .preflight import run_preflight, verify_public_identity_continuity
from .rollback import (
    explicit_rollback_services,
    inject_and_verify_service_rollback as _inject_and_verify_service_rollback,
    rollback_to_previous as _rollback_to_previous,
)


STACK_NAME = "felix-new"
RECEIPT_DIRECTORY = Path("build") / "release-evidence" / "swarm" / "felix"
DIGEST_PATTERN = re.compile(r"@sha256:[0-9a-f]{64}$")


def _utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp.

    Returns:
        Timestamp ending in ``Z``.
    """

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_operation_id() -> str:
    """Create a sortable public release operation identifier.

    Returns:
        UTC timestamp plus random hexadecimal suffix.
    """

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid.uuid4().hex[:12]}"


def _write_receipt(root: Path, receipt: ReleaseReceipt) -> Path:
    """Atomically retain one sanitized release receipt.

    Args:
        root: Swarm repository root.
        receipt: Sanitized state-machine receipt.

    Returns:
        Final ignored receipt path.

    Raises:
        FelixReleaseError: If the receipt cannot be protected and retained.

    Side Effects:
        Writes one mode-0600 JSON file below ``build/release-evidence``.
    """

    directory = root / RECEIPT_DIRECTORY
    final_path = directory / f"{receipt.operation_id}.json"
    temporary = directory / f".{receipt.operation_id}.tmp"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(receipt.as_dict(), indent=2, sort_keys=True) + "\n"
        if SENSITIVE_LOG_PATTERN.search(serialized):
            raise FelixReleaseError("Sanitized receipt failed secret-pattern scan.")
        temporary.write_text(serialized, encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(final_path)
    except OSError as exc:
        raise FelixReleaseError("Unable to retain sanitized release receipt.") from exc
    return final_path


def _wait_for_health(
    runner: CommandRunner,
    image: ImageIdentity,
    web_image: ImageIdentity,
    profile: FelixSiteProfile,
    *,
    timeout_seconds: int = 240,
) -> HealthEvidence:
    """Retry strict health until success or timeout.

    Args:
        runner: Shell-free command runner.
        image: Expected immutable candidate API image.
        web_image: Expected immutable candidate WebApp image.
        profile: Validated Felix site profile.
        timeout_seconds: Maximum wait duration.

    Returns:
        Strict health evidence.

    Raises:
        FelixReleaseError: If health never converges.
    """

    deadline = time.monotonic() + timeout_seconds
    last_error: FelixReleaseError | None = None
    while time.monotonic() < deadline:
        try:
            return run_strict_health(runner, image, web_image, profile)
        except FelixReleaseError as exc:
            last_error = exc
            time.sleep(5)
    if last_error is not None:
        raise FelixReleaseError(f"Strict health timed out: {last_error}") from last_error
    raise FelixReleaseError("Strict health timed out without an observation.")


def _failure_injection_image(profile: FelixSiteProfile) -> str:
    """Resolve the digest-pinned incompatible image used by rollback drills.

    Args:
        profile: Validated Felix site profile.

    Returns:
        Digest-pinned Redis image reference.

    Raises:
        FelixReleaseError: If the services declaration or digest is invalid.
    """

    services = profile.data["services"]
    if not isinstance(services, dict):
        raise FelixReleaseError("Felix services profile is not an object.")
    bad_image = str(services["redisImage"])
    if not DIGEST_PATTERN.search(bad_image):
        raise FelixReleaseError("Failure-injection image is not digest pinned.")
    return bad_image


def _drill_public_service_rollbacks(
    runner: CommandRunner,
    previous: PreviousDeployment,
    bad_image: str,
) -> dict[str, dict[str, Any]]:
    """Inject and prove independent API and WebApp automatic rollbacks.

    Args:
        runner: Shell-free command runner.
        previous: Captured healthy public-service state.
        bad_image: Digest-pinned incompatible image.

    Returns:
        Component-keyed automatic rollback evidence.

    Raises:
        FelixReleaseError: If required prior image identity is incomplete or
            either rollback does not complete exactly.
    """

    api_reference = previous.image_reference
    api_digest = previous.image_digest
    web_reference = previous.web_image_reference
    web_digest = previous.web_image_digest
    if (
        not api_reference
        or not api_digest
        or not web_reference
        or not web_digest
    ):
        raise FelixReleaseError("Rollback drill prior image identity is incomplete.")
    return {
        "api": _inject_and_verify_service_rollback(
            runner,
            API_SERVICE,
            "api",
            api_reference,
            api_digest,
            bad_image,
        ),
        "web": _inject_and_verify_service_rollback(
            runner,
            WEB_SERVICE,
            "web",
            web_reference,
            web_digest,
            bad_image,
        ),
    }


def _redacted_service_logs(
    runner: CommandRunner,
    service_name: str,
) -> str:
    """Read and redact one candidate public service's recent logs.

    Args:
        runner: Shell-free command runner.
        service_name: Exact candidate Docker service name.

    Returns:
        Recent logs with credential and bearer values replaced.
    """

    result = runner.run(
        ["docker", "service", "logs", "--raw", "--tail", "200", service_name],
        check=False,
    )
    combined = f"{result.stdout}\n{result.stderr}"
    redacted = re.sub(
        r"(?i)((password|client_secret|api_key|private_key)\s*[:=]\s*)\S+",
        r"\1[REDACTED]",
        combined,
    )
    return re.sub(
        r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?|bearer\s+)\S+",
        r"\1[REDACTED]",
        redacted,
    )


class FelixReleaseStateMachine:
    """Own strict, candidate-only Swarm release transitions."""

    def __init__(self, root: Path, runner: CommandRunner | None = None) -> None:
        """Initialize the state machine.

        Args:
            root: Swarm repository root.
            runner: Optional shell-free runner for testing.
        """

        self.root = root.resolve()
        self.runner = runner or CommandRunner()

    def preflight(self) -> tuple[PreflightEvidence, Path]:
        """Run strict preflight and retain a sanitized receipt.

        Returns:
            Preflight evidence and receipt path.
        """

        receipt = ReleaseReceipt(_new_operation_id(), _utc_timestamp())
        receipt.events.append("preflight-started")
        receipt.preflight = run_preflight(self.root, self.runner)
        receipt.state = "preflight-passed"
        receipt.events.append("preflight-passed")
        return receipt.preflight, _write_receipt(self.root, receipt)

    def deploy(self) -> Path:
        """Backup, deploy the digest-bound candidate, and require strict health.

        Returns:
            Sanitized successful or rolled-back receipt path.

        Raises:
            FelixReleaseError: If any gate fails. A post-deploy failure triggers
                candidate-only rollback before the exception is returned.

        Side Effects:
            Pulls images, writes backup/receipt artifacts, deploys stack
            ``felix-new``, and may rollback that candidate.
        """

        receipt = ReleaseReceipt(_new_operation_id(), _utc_timestamp())
        try:
            receipt.events.append("preflight-started")
            receipt.preflight = run_preflight(self.root, self.runner)
            receipt.events.append("preflight-passed")
            profile = load_felix_site_profile(self.root)
            receipt.previous = capture_previous_deployment(self.runner)
            receipt.backup = create_verified_backup(
                self.runner,
                profile,
                receipt.previous,
                receipt.operation_id,
            )
            receipt.events.append("backup-verified")
            receipt.events.append("candidate-deploy-started")
            self.runner.run(
                [
                    "docker",
                    "stack",
                    "deploy",
                    "--compose-file",
                    str(receipt.preflight.stack_path),
                    "--with-registry-auth",
                    "--prune",
                    STACK_NAME,
                ]
            )
            receipt.events.append("candidate-deployed")
            if receipt.preflight.web_image is None:
                raise FelixReleaseError("Preflight omitted the WebApp image.")
            receipt.health = _wait_for_health(
                self.runner,
                receipt.preflight.image,
                receipt.preflight.web_image,
                profile,
            )
            receipt.events.append("strict-health-passed")
            verify_public_identity_continuity()
            receipt.events.append("legacy-continuity-passed")
            receipt.state = "healthy"
            return _write_receipt(self.root, receipt)
        except FelixReleaseError:
            if (
                receipt.previous is not None
                and "candidate-deploy-started" in receipt.events
            ):
                try:
                    receipt.rollback = _rollback_to_previous(
                        self.runner,
                        receipt.previous,
                    )
                    receipt.events.append("rollback-completed")
                    receipt.state = "rolled-back"
                except FelixReleaseError as rollback_error:
                    receipt.events.append("rollback-failed")
                    receipt.state = "rollback-failed"
                    _write_receipt(self.root, receipt)
                    raise FelixReleaseError(
                        "Candidate deployment failed and rollback did not complete."
                    ) from rollback_error
                _write_receipt(self.root, receipt)
            else:
                receipt.state = "failed-before-deploy"
                _write_receipt(self.root, receipt)
            raise

    def health(self) -> tuple[HealthEvidence, Path]:
        """Run strict health for the currently selected published image.

        Returns:
            Health evidence and sanitized receipt path.
        """

        receipt = ReleaseReceipt(_new_operation_id(), _utc_timestamp())
        receipt.preflight = run_preflight(self.root, self.runner)
        if receipt.preflight.web_image is None:
            raise FelixReleaseError("Preflight omitted the WebApp image.")
        profile = load_felix_site_profile(self.root)
        receipt.health = run_strict_health(
            self.runner,
            receipt.preflight.image,
            receipt.preflight.web_image,
            profile,
        )
        verify_public_identity_continuity()
        receipt.state = "healthy"
        receipt.events.extend(
            [
                "preflight-passed",
                "strict-health-passed",
                "legacy-continuity-passed",
            ]
        )
        return receipt.health, _write_receipt(self.root, receipt)

    def rollback(self) -> Path:
        """Explicitly rollback both candidate public services.

        Returns:
            Sanitized rollback receipt path.

        Raises:
            FelixReleaseError: If no rollback-capable public service exists or
                either requested rollback cannot be proven.

        Side Effects:
            Rolls back `felix-new_web` and `felix-new_api` when present.
        """

        current = capture_previous_deployment(self.runner)
        receipt = ReleaseReceipt(_new_operation_id(), _utc_timestamp())
        receipt.previous = current
        restored_services = explicit_rollback_services(self.runner, current)
        receipt.rollback = {
            "performed": True,
            "mode": "explicit-full-stack-service-rollback",
            "services": restored_services,
        }
        receipt.events.append("explicit-rollback-completed")
        receipt.state = "rolled-back"
        return _write_receipt(self.root, receipt)

    def failure_injection_drill(self) -> Path:
        """Prove WebApp/API automatic rollback plus data continuity.

        Returns:
            Sanitized successful drill receipt path.

        Raises:
            FelixReleaseError: If Docker does not report automatic rollback to
                the prior digest, post-rollback health fails, or data is lost.

        Side Effects:
            Inserts one database marker, injects the pinned Redis image into
            each public service in turn, proves both automatic rollbacks, and
            retains data-continuity evidence.
        """

        receipt = ReleaseReceipt(_new_operation_id(), _utc_timestamp())
        receipt.preflight = run_preflight(self.root, self.runner)
        profile = load_felix_site_profile(self.root)
        receipt.previous = capture_previous_deployment(self.runner)
        if (
            not receipt.previous.service_exists
            or not receipt.previous.image_reference
            or not receipt.previous.image_digest
            or not receipt.previous.web_service_exists
            or not receipt.previous.web_image_reference
            or not receipt.previous.web_image_digest
            or receipt.preflight.web_image is None
        ):
            raise FelixReleaseError(
                "Rollback drill requires healthy prior WebApp and API digests."
            )
        receipt.health = run_strict_health(
            self.runner,
            receipt.preflight.image,
            receipt.preflight.web_image,
            profile,
        )
        marker = uuid.uuid4().hex
        create_continuity_marker(self.runner, profile, marker)
        service_rollbacks = _drill_public_service_rollbacks(
            self.runner,
            receipt.previous,
            _failure_injection_image(profile),
        )
        receipt.events.append("bad-candidates-update-attempted")
        receipt.rollback = {
            "performed": True,
            "mode": "automatic-full-stack-service-rollback",
            "services": service_rollbacks,
        }
        receipt.health = _wait_for_health(
            self.runner,
            receipt.preflight.image,
            receipt.preflight.web_image,
            profile,
        )
        verify_public_identity_continuity()
        verify_continuity_marker(self.runner, profile, marker)
        receipt.rollback["dataContinuityMarkerSha256"] = hashlib.sha256(
            marker.encode()
        ).hexdigest()
        receipt.rollback["dataContinuityVerified"] = True
        receipt.events.extend(
            [
                "rollback-completed",
                "legacy-continuity-passed",
                "data-continuity-verified",
            ]
        )
        receipt.state = "rollback-drill-passed"
        return _write_receipt(self.root, receipt)

    def status(self) -> dict[str, Any]:
        """Return sanitized candidate stack/service state.

        Returns:
            Public stack plus WebApp/API image state.
        """

        previous = capture_previous_deployment(self.runner)
        return {
            "schemaVersion": 2,
            "kind": "felix-swarm-status",
            "stackName": STACK_NAME,
            **previous.as_dict(),
        }

    def sanitized_logs(self) -> str:
        """Return recent WebApp/API logs with conservative redaction.

        Returns:
            Component-labeled log text with sensitive assignments replaced.
        """

        sections = (
            ("WebApp", WEB_SERVICE),
            ("API", API_SERVICE),
        )
        return "".join(
            f"===== {label} =====\n"
            f"{_redacted_service_logs(self.runner, service_name)}"
            for label, service_name in sections
        )
