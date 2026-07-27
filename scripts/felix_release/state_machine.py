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

from felix_site_contract import load_felix_site_profile

from .backup import (
    API_SERVICE,
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


def _current_api_image(runner: CommandRunner) -> str | None:
    """Read the deployed candidate API image reference.

    Args:
        runner: Shell-free command runner.

    Returns:
        Image reference, or None when the service is absent.
    """

    result = runner.run(
        [
            "docker",
            "service",
            "inspect",
            API_SERVICE,
            "--format",
            "{{json .Spec.TaskTemplate.ContainerSpec.Image}}",
        ],
        check=False,
    )
    if result.return_code != 0:
        return None
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise FelixReleaseError("Current API service image is invalid JSON.") from exc
    return str(value)


def _wait_for_image(
    runner: CommandRunner,
    expected_image: str,
    *,
    timeout_seconds: int = 180,
) -> None:
    """Wait until the API service reports an exact image reference.

    Args:
        runner: Shell-free command runner.
        expected_image: Exact prior or candidate digest reference.
        timeout_seconds: Maximum wait duration.

    Returns:
        None.

    Raises:
        FelixReleaseError: If the expected image does not become active.
    """

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _current_api_image(runner) == expected_image:
            return
        time.sleep(2)
    raise FelixReleaseError("Timed out waiting for the expected API service image.")


def _wait_for_health(
    runner: CommandRunner,
    image: ImageIdentity,
    *,
    timeout_seconds: int = 240,
) -> HealthEvidence:
    """Retry strict health until success or timeout.

    Args:
        runner: Shell-free command runner.
        image: Expected immutable candidate image.
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
            return run_strict_health(runner, image)
        except FelixReleaseError as exc:
            last_error = exc
            time.sleep(5)
    if last_error is not None:
        raise FelixReleaseError(f"Strict health timed out: {last_error}") from last_error
    raise FelixReleaseError("Strict health timed out without an observation.")


def _rollback_to_previous(
    runner: CommandRunner,
    previous: PreviousDeployment,
) -> dict[str, Any]:
    """Rollback only the candidate stack/service to its captured prior state.

    Args:
        runner: Shell-free command runner.
        previous: Captured pre-deployment candidate state.

    Returns:
        Sanitized rollback result.

    Raises:
        FelixReleaseError: If rollback cannot restore the exact prior image.

    Side Effects:
        Rolls back the candidate API service, or removes a failed first-time
        candidate stack when no prior candidate existed.
    """

    if previous.service_exists and previous.image_reference:
        runner.run(
            [
                "docker",
                "service",
                "rollback",
                "--detach=false",
                API_SERVICE,
            ]
        )
        _wait_for_image(runner, previous.image_reference)
        return {
            "performed": True,
            "mode": "service-rollback",
            "restoredImage": previous.image_reference,
            "priorDigest": previous.image_digest,
        }
    runner.run(["docker", "stack", "rm", STACK_NAME])
    return {
        "performed": True,
        "mode": "remove-failed-first-candidate",
        "restoredImage": None,
        "priorDigest": None,
    }


def _wait_for_automatic_rollback(
    runner: CommandRunner,
    previous: PreviousDeployment,
    prior_service_version: int,
    *,
    timeout_seconds: int = 240,
) -> dict[str, Any]:
    """Require Docker to complete rollback to the exact captured image.

    Args:
        runner: Shell-free command runner.
        previous: Exact healthy state captured before failure injection.
        prior_service_version: Docker service version before failure injection.
        timeout_seconds: Maximum wait duration.

    Returns:
        Sanitized automatic-rollback evidence.

    Raises:
        FelixReleaseError: If Docker does not report ``rollback_completed`` at
            the exact prior image before timeout.
    """

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        inspected = runner.run(
            ["docker", "service", "inspect", API_SERVICE, "--format", "{{json .}}"],
            check=False,
        )
        if inspected.return_code == 0:
            try:
                service = json.loads(inspected.stdout)
            except json.JSONDecodeError:
                service = {}
            image = (
                service.get("Spec", {})
                .get("TaskTemplate", {})
                .get("ContainerSpec", {})
                .get("Image")
            )
            state = service.get("UpdateStatus", {}).get("State")
            version = service.get("Version", {}).get("Index")
            if (
                state == "rollback_completed"
                and image == previous.image_reference
                and isinstance(version, int)
                and version > prior_service_version
            ):
                return {
                    "performed": True,
                    "mode": "automatic-service-rollback",
                    "restoredImage": image,
                    "priorDigest": previous.image_digest,
                    "dockerUpdateState": state,
                }
        time.sleep(2)
    raise FelixReleaseError("Docker did not complete automatic rollback safely.")


def _service_version(runner: CommandRunner) -> int:
    """Read the candidate API service version before failure injection.

    Args:
        runner: Shell-free command runner.

    Returns:
        Positive Docker service specification version.

    Raises:
        FelixReleaseError: If the version is unavailable or invalid.
    """

    result = runner.run(
        [
            "docker",
            "service",
            "inspect",
            API_SERVICE,
            "--format",
            "{{json .Version.Index}}",
        ]
    )
    try:
        version = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise FelixReleaseError("Candidate API service version is invalid.") from exc
    if not isinstance(version, int) or version < 1:
        raise FelixReleaseError("Candidate API service version is invalid.")
    return version


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
            receipt.health = _wait_for_health(self.runner, receipt.preflight.image)
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
        receipt.health = run_strict_health(self.runner, receipt.preflight.image)
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
        """Explicitly invoke Docker's candidate API service rollback.

        Returns:
            Sanitized rollback receipt path.

        Raises:
            FelixReleaseError: If no rollback-capable service exists.

        Side Effects:
            Rolls back only ``felix-new_api`` to Docker's prior service spec.
        """

        current = capture_previous_deployment(self.runner)
        if not current.service_exists:
            raise FelixReleaseError("Candidate API service does not exist.")
        receipt = ReleaseReceipt(_new_operation_id(), _utc_timestamp())
        receipt.previous = current
        self.runner.run(
            ["docker", "service", "rollback", "--detach=false", API_SERVICE]
        )
        restored = _current_api_image(self.runner)
        if not restored or restored == current.image_reference:
            raise FelixReleaseError("Explicit rollback did not change the API image.")
        receipt.rollback = {
            "performed": True,
            "mode": "explicit-service-rollback",
            "replacedImage": current.image_reference,
            "restoredImage": restored,
        }
        receipt.events.append("explicit-rollback-completed")
        receipt.state = "rolled-back"
        return _write_receipt(self.root, receipt)

    def failure_injection_drill(self) -> Path:
        """Inject a pinned non-API image and prove rollback plus data continuity.

        Returns:
            Sanitized successful drill receipt path.

        Raises:
            FelixReleaseError: If Docker does not report automatic rollback to
                the prior digest, post-rollback health fails, or data is lost.

        Side Effects:
            Inserts one isolated database marker, temporarily updates the
            candidate API service to the profile's pinned Redis image, requires
            Docker's automatic rollback, and retains a receipt.
        """

        receipt = ReleaseReceipt(_new_operation_id(), _utc_timestamp())
        receipt.preflight = run_preflight(self.root, self.runner)
        profile = load_felix_site_profile(self.root)
        receipt.previous = capture_previous_deployment(self.runner)
        if not receipt.previous.service_exists or not receipt.previous.image_digest:
            raise FelixReleaseError("Rollback drill requires a healthy prior digest.")
        receipt.health = run_strict_health(self.runner, receipt.preflight.image)
        marker = uuid.uuid4().hex
        create_continuity_marker(self.runner, profile, marker)
        services = profile.data["services"]
        if not isinstance(services, dict):
            raise FelixReleaseError("Felix services profile is not an object.")
        bad_image = str(services["redisImage"])
        if not DIGEST_PATTERN.search(bad_image):
            raise FelixReleaseError("Failure-injection image is not digest pinned.")
        prior_service_version = _service_version(self.runner)
        update_result = self.runner.run(
            [
                "docker",
                "service",
                "update",
                "--image",
                bad_image,
                "--detach=false",
                "--update-order",
                "start-first",
                "--update-failure-action",
                "rollback",
                API_SERVICE,
            ],
            check=False,
        )
        receipt.events.append("bad-candidate-update-attempted")
        receipt.rollback = _wait_for_automatic_rollback(
            self.runner,
            receipt.previous,
            prior_service_version,
        )
        receipt.rollback["updateCommandExitCode"] = update_result.return_code
        receipt.health = _wait_for_health(self.runner, receipt.preflight.image)
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
            Public stack and API image state.
        """

        previous = capture_previous_deployment(self.runner)
        return {
            "schemaVersion": 1,
            "kind": "felix-swarm-status",
            "stackName": STACK_NAME,
            **previous.as_dict(),
        }

    def sanitized_logs(self) -> str:
        """Return recent API logs with conservative value redaction.

        Returns:
            Recent log text with sensitive assignments replaced.
        """

        result = self.runner.run(
            ["docker", "service", "logs", "--raw", "--tail", "200", API_SERVICE],
            check=False,
        )
        combined = f"{result.stdout}\n{result.stderr}"
        redacted = re.sub(
            r"(?i)((password|client_secret|api_key|private_key)\s*[:=]\s*)\S+",
            r"\1[REDACTED]",
            combined,
        )
        redacted = re.sub(
            r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?|bearer\s+)\S+",
            r"\1[REDACTED]",
            redacted,
        )
        return redacted
