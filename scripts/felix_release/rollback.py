"""Candidate-only WebApp/API rollback and failure-injection helpers.

The module restores only services in the isolated `felix-new` stack. It never
targets legacy stacks, routes, realms, or application data.
"""

from __future__ import annotations

import json
import time
from typing import Any

from .backup import API_SERVICE, WEB_SERVICE
from .command import CommandRunner
from .errors import FelixReleaseError
from .models import PreviousDeployment


_STACK_NAME = "felix-new"


def current_service_image(
    runner: CommandRunner,
    service_name: str,
    component: str,
) -> str | None:
    """Read one deployed candidate public-service image reference.

    Args:
        runner: Shell-free command runner.
        service_name: Exact candidate Docker service name.
        component: Human-readable component used in diagnostics.

    Returns:
        Image reference, or None when the service is absent.

    Raises:
        FelixReleaseError: If Docker returns malformed image JSON.
    """

    result = runner.run(
        [
            "docker",
            "service",
            "inspect",
            service_name,
            "--format",
            "{{json .Spec.TaskTemplate.ContainerSpec.Image}}",
        ],
        check=False,
    )
    if result.return_code != 0:
        return None
    try:
        return str(json.loads(result.stdout))
    except json.JSONDecodeError as exc:
        raise FelixReleaseError(
            f"Current {component} service image is invalid JSON."
        ) from exc


def _wait_for_image(
    runner: CommandRunner,
    service_name: str,
    component: str,
    expected_image: str,
    *,
    timeout_seconds: int = 180,
) -> None:
    """Wait for one service to report an exact image reference.

    Args:
        runner: Shell-free command runner.
        service_name: Exact candidate Docker service name.
        component: Human-readable component used in diagnostics.
        expected_image: Exact prior digest reference.
        timeout_seconds: Maximum wait duration.

    Returns:
        None.

    Raises:
        FelixReleaseError: If the expected image does not become active.
    """

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if current_service_image(runner, service_name, component) == expected_image:
            return
        time.sleep(2)
    raise FelixReleaseError(
        f"Timed out waiting for the expected {component} service image."
    )


def _restore_service(
    runner: CommandRunner,
    component: str,
    service_name: str,
    existed: bool,
    reference: str | None,
    digest: str | None,
) -> dict[str, Any]:
    """Restore or remove one public service according to prior state.

    Args:
        runner: Shell-free command runner.
        component: Public component name.
        service_name: Exact candidate Docker service name.
        existed: Whether the service existed before deployment.
        reference: Prior image reference.
        digest: Prior immutable digest.

    Returns:
        Sanitized component rollback evidence.
    """

    if existed and reference:
        runner.run(
            ["docker", "service", "rollback", "--detach=false", service_name]
        )
        _wait_for_image(runner, service_name, component, reference)
        return {
            "action": "service-rollback",
            "restoredImage": reference,
            "priorDigest": digest,
        }
    runner.run(["docker", "service", "rm", service_name], check=False)
    return {
        "action": "remove-new-service",
        "restoredImage": None,
        "priorDigest": None,
    }


def rollback_to_previous(
    runner: CommandRunner,
    previous: PreviousDeployment,
) -> dict[str, Any]:
    """Restore both public services or remove a failed first candidate.

    Args:
        runner: Shell-free command runner.
        previous: Captured pre-deployment candidate state.

    Returns:
        Sanitized full-stack rollback evidence.
    """

    if not previous.stack_exists:
        runner.run(["docker", "stack", "rm", _STACK_NAME])
        return {
            "performed": True,
            "mode": "remove-failed-first-candidate",
            "services": {},
        }
    services = {
        "api": _restore_service(
            runner,
            "api",
            API_SERVICE,
            previous.service_exists,
            previous.image_reference,
            previous.image_digest,
        ),
        "web": _restore_service(
            runner,
            "web",
            WEB_SERVICE,
            previous.web_service_exists,
            previous.web_image_reference,
            previous.web_image_digest,
        ),
    }
    return {
        "performed": True,
        "mode": "full-stack-service-rollback",
        "services": services,
    }


def _rollback_observation(
    runner: CommandRunner,
    service_name: str,
) -> tuple[str | None, str | None, int | None]:
    """Read image, update state, and version for one rollback attempt.

    Args:
        runner: Shell-free command runner.
        service_name: Exact candidate Docker service name.

    Returns:
        Image reference, Docker update state, and service version.
    """

    inspected = runner.run(
        ["docker", "service", "inspect", service_name, "--format", "{{json .}}"],
        check=False,
    )
    if inspected.return_code != 0:
        return None, None, None
    try:
        service = json.loads(inspected.stdout)
    except json.JSONDecodeError:
        return None, None, None
    image = (
        service.get("Spec", {})
        .get("TaskTemplate", {})
        .get("ContainerSpec", {})
        .get("Image")
    )
    state = service.get("UpdateStatus", {}).get("State")
    version = service.get("Version", {}).get("Index")
    return image, state, version


def _wait_for_automatic_rollback(
    runner: CommandRunner,
    service_name: str,
    component: str,
    previous_reference: str,
    previous_digest: str,
    prior_service_version: int,
    *,
    timeout_seconds: int = 240,
) -> dict[str, Any]:
    """Require Docker to complete one exact automatic rollback.

    Args:
        runner: Shell-free command runner.
        service_name: Exact candidate service under test.
        component: Human-readable component used in diagnostics.
        previous_reference: Exact healthy image before injection.
        previous_digest: Exact healthy digest before injection.
        prior_service_version: Docker service version before injection.
        timeout_seconds: Maximum wait duration.

    Returns:
        Sanitized automatic rollback evidence.

    Raises:
        FelixReleaseError: If rollback does not complete exactly.
    """

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        image, state, version = _rollback_observation(runner, service_name)
        if (
            state == "rollback_completed"
            and image == previous_reference
            and isinstance(version, int)
            and version > prior_service_version
        ):
            return {
                "performed": True,
                "mode": "automatic-service-rollback",
                "component": component,
                "restoredImage": image,
                "priorDigest": previous_digest,
                "dockerUpdateState": state,
            }
        time.sleep(2)
    raise FelixReleaseError(
        f"Docker did not complete automatic {component} rollback safely."
    )


def _service_version(
    runner: CommandRunner,
    service_name: str,
    component: str,
) -> int:
    """Read one candidate service version before failure injection.

    Args:
        runner: Shell-free command runner.
        service_name: Exact candidate Docker service name.
        component: Human-readable component used in diagnostics.

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
            service_name,
            "--format",
            "{{json .Version.Index}}",
        ]
    )
    try:
        version = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise FelixReleaseError(
            f"Candidate {component} service version is invalid."
        ) from exc
    if not isinstance(version, int) or version < 1:
        raise FelixReleaseError(f"Candidate {component} service version is invalid.")
    return version


def inject_and_verify_service_rollback(
    runner: CommandRunner,
    service_name: str,
    component: str,
    previous_reference: str,
    previous_digest: str,
    bad_image: str,
) -> dict[str, Any]:
    """Inject one incompatible image and prove automatic rollback.

    Args:
        runner: Shell-free command runner.
        service_name: Exact candidate service under test.
        component: Human-readable component label.
        previous_reference: Exact healthy image before injection.
        previous_digest: Exact healthy digest before injection.
        bad_image: Digest-pinned incompatible image used for the drill.

    Returns:
        Sanitized automatic rollback evidence including update exit code.
    """

    prior_version = _service_version(runner, service_name, component)
    update_result = runner.run(
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
            service_name,
        ],
        check=False,
    )
    evidence = _wait_for_automatic_rollback(
        runner,
        service_name,
        component,
        previous_reference,
        previous_digest,
        prior_version,
    )
    evidence["updateCommandExitCode"] = update_result.return_code
    return evidence


def explicit_rollback_services(
    runner: CommandRunner,
    current: PreviousDeployment,
) -> dict[str, dict[str, str]]:
    """Rollback every present public service and prove its image changed.

    Args:
        runner: Shell-free command runner.
        current: Candidate public-service state before explicit rollback.

    Returns:
        Component-keyed replaced and restored image references.

    Raises:
        FelixReleaseError: If no service exists or a rollback is ineffective.
    """

    candidates = (
        ("api", API_SERVICE, current.service_exists, current.image_reference),
        ("web", WEB_SERVICE, current.web_service_exists, current.web_image_reference),
    )
    restored_services: dict[str, dict[str, str]] = {}
    for component, service_name, exists, replaced in candidates:
        if not exists or not replaced:
            continue
        runner.run(["docker", "service", "rollback", "--detach=false", service_name])
        restored = current_service_image(runner, service_name, component)
        if not restored or restored == replaced:
            raise FelixReleaseError(
                f"Explicit rollback did not change the {component} image."
            )
        restored_services[component] = {
            "replacedImage": replaced,
            "restoredImage": restored,
        }
    if not restored_services:
        raise FelixReleaseError("Candidate public services do not exist.")
    return restored_services
